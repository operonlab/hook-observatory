#!/usr/bin/env python3
"""
ws_qwen_quota_sync.py — Sync Qwen DashScope free quota via Playwright CLI

Scrapes https://modelstudio.console.alibabacloud.com free-quota dashboard,
parses usage data, and stores in Redis for agent-metrics consumption.

Requires: Alibaba Cloud session in Playwright master profile.

Logs: ~/workshop/outputs/scheduler/logs/ws-qwen-quota-sync.log
"""

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
PYTHON = HOME / ".local/bin/python3"
PW_SESSION = HOME / ".claude/scripts/pw_session.py"
LOG_DIR = HOME / "workshop/outputs/scheduler/logs"
LOG_FILE = LOG_DIR / "ws-qwen-quota-sync.log"
REDIS_KEY = "agent-metrics:qwen:free_quota"
REDIS_TTL = 86400 * 7  # 7 days (free quota changes slowly)
TARGET_URL = (
    "https://modelstudio.console.alibabacloud.com/ap-southeast-1/"
    "?tab=dashboard#/model-usage/free-quota"
)

os.environ["PATH"] = (
    f"/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:"
    f"/usr/sbin:/sbin:{HOME}/.local/bin:{os.environ.get('PATH', '')}"
)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def scrape_with_playwright() -> str | None:
    """Scrape DashScope free quota page via Playwright CLI."""
    # Init session (APFS clone of master profile)
    init_result = subprocess.run(
        [str(PYTHON), str(PW_SESSION), "init"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    profile_dir = None
    sid = None
    for line in init_result.stdout.splitlines():
        if line.startswith("export PW_PROFILE="):
            profile_dir = line.split("=", 1)[1].strip().strip("'\"")
        elif line.startswith("export SID="):
            sid = line.split("=", 1)[1].strip().strip("'\"")

    if not profile_dir or not sid:
        log(f"ERROR: pw_session init failed: {init_result.stdout[:200]}")
        return None

    session_id = f"{sid}-qwen"
    try:
        # Open page
        subprocess.run(
            [
                "npx",
                "@playwright/cli",
                "--profile",
                profile_dir,
                f"-s={session_id}",
                "open",
                TARGET_URL,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        import time

        time.sleep(5)  # Wait for SPA to render

        # Extract body text
        eval_result = subprocess.run(
            [
                "npx",
                "@playwright/cli",
                f"-s={session_id}",
                "eval",
                "document.body.innerText.substring(0, 8000)",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        # Close + cleanup
        subprocess.run(
            ["npx", "@playwright/cli", f"-s={session_id}", "close"],
            capture_output=True,
            timeout=10,
        )
        subprocess.run(
            [str(PYTHON), str(PW_SESSION), "cleanup", profile_dir],
            capture_output=True,
            timeout=10,
        )

        if eval_result.returncode != 0:
            log(f"ERROR: eval failed: {eval_result.stderr[:200]}")
            return None

        # Decode JSON-wrapped string from Playwright CLI
        text = eval_result.stdout
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith('"') and stripped.endswith('"') and len(stripped) > 100:
                try:
                    decoded = json.loads(stripped)
                    if isinstance(decoded, str):
                        return decoded
                except (json.JSONDecodeError, ValueError):
                    pass
        return text

    except subprocess.TimeoutExpired:
        log("ERROR: playwright timeout")
        return None
    except Exception as e:
        log(f"ERROR: playwright failed: {e}")
        return None
    finally:
        # Ensure cleanup
        try:
            subprocess.run(
                ["npx", "@playwright/cli", f"-s={session_id}", "close"],
                capture_output=True,
                timeout=5,
            )
            subprocess.run(
                [str(PYTHON), str(PW_SESSION), "cleanup", profile_dir],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass


def scrape_with_safari() -> str | None:
    """Fallback: use Safari osascript to get page content."""
    safari_exec = HOME / ".claude/scripts/safari_exec.py"
    if not safari_exec.exists():
        return None
    try:
        # Navigate
        subprocess.run(
            [str(PYTHON), str(safari_exec), "nav", TARGET_URL],
            capture_output=True,
            text=True,
            timeout=15,
        )
        import time

        time.sleep(5)

        # Extract text
        result = subprocess.run(
            [str(PYTHON), str(safari_exec), "eval", "document.body.innerText.substring(0, 8000)"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except Exception as e:
        log(f"ERROR: safari fallback failed: {e}")
    return None


def parse_free_quota(text: str) -> dict | None:
    """Parse DashScope free quota page text (supports both Chinese and English UI).

    Chinese patterns:
      "95\n模型总数", "剩999,961/共1,000,000"
    English patterns:
      "95\nTotal Number of Models", "Remaining 999,961 / Total 1,000,000"
      "Remaining999,961/Total1,000,000" (table format, no spaces)
    """
    if not text or len(text) < 50:
        return None

    result = {
        "total_models": 0,
        "healthy": 0,
        "over_50pct": 0,
        "over_80pct": 0,
        "no_free": 0,
        "top_models": [],
        "synced_at": datetime.now(UTC).isoformat(),
    }

    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            # Total models: CN "模型总数" / EN "Total Number of Models"
            if (
                "模型总数" in next_line
                or "模型總數" in next_line
                or "Total Number of Models" in next_line
            ):
                try:
                    result["total_models"] = int(stripped.replace(",", ""))
                except ValueError:
                    pass
            # Healthy: CN "额度充沛" / EN "Sufficient quota"
            elif (
                "额度充沛" in next_line
                or "額度充沛" in next_line
                or "Sufficient quota" in next_line
            ):
                try:
                    result["healthy"] = int(stripped.replace(",", ""))
                except ValueError:
                    pass
            # Over 50%: CN "使用超50%" / EN "over 50% used"
            elif "使用超50%" in next_line or "over 50% used" in next_line:
                try:
                    result["over_50pct"] = int(stripped.replace(",", ""))
                except ValueError:
                    pass
            # Over 80%: CN "使用超80%" / EN "over 80% used"
            elif "使用超80%" in next_line or "over 80% used" in next_line:
                try:
                    result["over_80pct"] = int(stripped.replace(",", ""))
                except ValueError:
                    pass
            # No free quota: CN "无免费额度" / EN "no free quota"
            elif (
                "无免费额度" in next_line
                or "無免費額度" in next_line
                or "no free quota" in next_line
            ):
                try:
                    result["no_free"] = int(stripped.replace(",", ""))
                except ValueError:
                    pass

        # Parse model entries:
        #   CN: "剩999,961/共1,000,000"
        #   EN: "Remaining 999,961 / Total 1,000,000" or "Remaining999,961/Total1,000,000"
        quota_match = re.search(r"剩([\d,]+)/共([\d,]+)", stripped)
        if not quota_match:
            quota_match = re.search(r"Remaining\s*([\d,]+)\s*/\s*Total\s*([\d,]+)", stripped)
        if quota_match and i > 0:
            remaining = int(quota_match.group(1).replace(",", ""))
            total = int(quota_match.group(2).replace(",", ""))
            model_name = ""
            for j in range(max(0, i - 3), i):
                candidate = lines[j].strip()
                if (
                    candidate
                    and not candidate.endswith("%")
                    and "剩" not in candidate
                    and "Remaining" not in candidate
                ):
                    model_name = candidate
            if model_name:
                result["top_models"].append(
                    {
                        "model": model_name,
                        "remaining": remaining,
                        "total": total,
                    }
                )

    if result["total_models"] > 0:
        return result
    return None


def store_to_redis(data: dict) -> bool:
    """Store parsed quota data to Redis."""
    try:
        import redis

        r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
        r.setex(REDIS_KEY, REDIS_TTL, json.dumps(data))
        return True
    except Exception as e:
        log(f"ERROR: Redis store failed: {e}")
        return False


def main() -> int:
    log("=== Qwen Free Quota Sync Start ===")

    # Try Playwright first, then Safari fallback
    text = scrape_with_playwright()
    if not text:
        log("Playwright failed, trying Safari fallback...")
        text = scrape_with_safari()

    if not text:
        log("ERROR: All scrape methods failed")
        return 1

    log(f"Scraped {len(text)} chars")

    data = parse_free_quota(text)
    if not data:
        log("ERROR: Failed to parse quota data from scraped text")
        log(f"Text preview: {text[:300]}")
        return 1

    log(
        f"Parsed: {data['total_models']} models, {data['healthy']} healthy, "
        f"{len(data['top_models'])} top models"
    )

    if store_to_redis(data):
        log(f"Stored to Redis ({REDIS_KEY}, TTL={REDIS_TTL}s)")
    else:
        # Fallback: write to /tmp
        fallback = Path("/tmp/agent-metrics-qwen-quota.json")
        fallback.write_text(json.dumps(data))
        log(f"Redis failed, wrote to {fallback}")

    log("=== Qwen Free Quota Sync Done ===")
    return 0


if __name__ == "__main__":
    import fcntl

    _lock_path = f"/tmp/{Path(__file__).stem}.lock"
    _lock_fd = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] Another instance already running (lock: {_lock_path})")
        sys.exit(0)
    sys.exit(main())

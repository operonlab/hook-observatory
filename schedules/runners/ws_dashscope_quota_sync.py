#!/usr/bin/env python3
"""
[DEPRECATED 2026-04-20] Replaced by `agent-metrics dashscope-quota-sync`
(stations/agent-metrics/src/collectors/dashscope_quota.rs).
the rename to agent-metrics is already in production; the wrapper is just the
cheapest path to fix today's OAuth gap while the Rust collector awaits
camoufox-based auth support.

Cronicle registry repointed to the Rust binary. Retained as 30-day rollback
reference; safe to delete after 2026-05-20.

Rollback:
  cd ~/workshop
  python3 schedules/scheduler.py remove ws-dashscope-quota-sync
  python3 schedules/scheduler.py add ws-dashscope-quota-sync \\
      "~/.local/bin/python3 ~/workshop/schedules/runners/ws_dashscope_quota_sync.py" \\
      '{"calendar": {"Hour": 18, "Minute": 30}}' "rollback to Python"

================================================================================
ws_dashscope_quota_sync.py — Sync DashScope (Qwen) free quota via camoufox-cli

Scrapes https://modelstudio.console.alibabacloud.com free-quota dashboard,
parses usage data, and stores in Redis for agent-metrics consumption.

Dual-track scraping: camoufox-cli (primary, anti-detect Firefox) →
playwright-cli (fallback) → Safari (last resort).

Requires: Alibaba Cloud session in camoufox master profile.

Logs: ~/workshop/outputs/scheduler/logs/ws-dashscope-quota-sync.log
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
PYTHON = HOME / ".local/bin/python3"
PW_SESSION = HOME / ".claude/scripts/pw_session.py"
LOG_DIR = HOME / "workshop/outputs/scheduler/logs"
LOG_FILE = LOG_DIR / "ws-dashscope-quota-sync.log"
REDIS_KEY = "agent-metrics:dashscope:free_quota"
REDIS_TTL = 86400 * 7  # 7 days (free quota changes slowly)
CFX_SESSION = "dashscope-sync"
COOKIES_FILE = HOME / ".camoufox-profiles/master-login-cookies.json"
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


def _cfx(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a camoufox-cli command with the sync session."""
    cmd = ["camoufox-cli", "--session", CFX_SESSION, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def scrape_with_camoufox() -> str | None:
    """Scrape DashScope free quota page via camoufox-cli (primary)."""
    try:
        # camoufox-cli only persists non-HttpOnly cookies to master profile;
        # Alibaba's login_aliyunid_ticket / JSESSIONID are HttpOnly. We export
        # them once after a manual OAuth login and re-import on every run.
        if COOKIES_FILE.exists():
            blank_r = _cfx("--persistent", "open", "about:blank")
            if blank_r.returncode != 0:
                log(f"ERROR: camoufox blank open failed: {blank_r.stderr[:200]}")
                return None
            imp_r = _cfx("cookies", "import", str(COOKIES_FILE))
            if imp_r.returncode != 0:
                log(f"WARN: cookies import failed: {imp_r.stderr[:200]}")
            open_r = _cfx("open", TARGET_URL)
        else:
            log("WARN: no master-login-cookies.json; relying on profile state")
            open_r = _cfx("--persistent", "open", TARGET_URL)
        if open_r.returncode != 0:
            log(f"ERROR: camoufox open failed: {open_r.stderr[:200]}")
            return None

        time.sleep(6)  # Wait for SPA to render

        eval_r = _cfx("eval", "document.body.innerText.substring(0, 8000)", timeout=15)

        if eval_r.returncode != 0:
            log(f"ERROR: camoufox eval failed: {eval_r.stderr[:200]}")
            return None

        return eval_r.stdout.strip() or None

    except subprocess.TimeoutExpired:
        log("ERROR: camoufox timeout")
        return None
    except FileNotFoundError:
        log("WARN: camoufox-cli not found, skipping")
        return None
    except Exception as e:
        log(f"ERROR: camoufox failed: {e}")
        return None
    finally:
        try:
            _cfx("close", timeout=10)
        except Exception:
            pass


def scrape_with_playwright() -> str | None:
    """Scrape DashScope free quota page via Playwright CLI (fallback)."""
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

    session_id = f"{sid}-dashscope"
    try:
        # Open page
        subprocess.run(
            [
                "playwright-cli",
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
        time.sleep(5)  # Wait for SPA to render

        # Extract body text
        eval_result = subprocess.run(
            [
                "playwright-cli",
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
            ["playwright-cli", f"-s={session_id}", "close"],
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
                ["playwright-cli", f"-s={session_id}", "close"],
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

    # Primary: camoufox-cli (anti-detect Firefox)
    text = scrape_with_camoufox()
    if not text:
        log("Camoufox failed, trying Playwright CLI fallback...")
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

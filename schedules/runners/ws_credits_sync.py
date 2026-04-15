#!/usr/bin/env python3
"""
ws_credits_sync.py — Unified LLM credits & quota sync

Runs three sections in sequence, sharing a single camoufox browser session
across all provider scrapes:

  1. Provider balance sync (MiniMax, Moonshot, Z.AI, DeepSeek, xAI)
  2. DashScope (Qwen) free quota sync
  3. Google Developer Program credits (NEW — scrapes billing console)

Replaces:
  - ws_provider_balance_sync.py (subprocess → inline)
  - ws_dashscope_quota_sync.py  (subprocess → inline)

Session strategy:
  - Single persistent camoufox session "credits-sync" shared by all 3 sections
  - Persistent Firefox profile holds all cookies (no domain isolation needed)
  - Session opened in Section 1, closed in main() finally block

Redis key patterns:
  - agent-metrics:provider:{name}:balance   (Section 1)
  - agent-metrics:provider:all_balances     (Section 1 summary)
  - agent-metrics:dashscope:free_quota      (Section 2)
  - agent-metrics:provider:google           (Section 3)

Logs: ~/workshop/outputs/scheduler/logs/ws-credits-sync.log
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
HOME = Path.home()
PYTHON = HOME / ".local/bin/python3"
PW_SESSION = HOME / ".claude/scripts/pw_session.py"
LOG_DIR = HOME / "workshop/outputs/scheduler/logs"
LOG_FILE = LOG_DIR / "ws-credits-sync.log"

REDIS_KEY_PREFIX = "agent-metrics:provider"
REDIS_TTL = 86400 * 7  # 7 days

# Single camoufox session for all providers (persistent profile holds all cookies)
CFX_SESSION = "credits-sync"

# Path fix so camoufox-cli and redis-cli are always found
os.environ["PATH"] = (
    f"/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:"
    f"/usr/sbin:/sbin:{HOME}/.local/bin:{os.environ.get('PATH', '')}"
)


# ── Logging ────────────────────────────────────────────────────────────────────


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── Redis helper ───────────────────────────────────────────────────────────────


def _get_redis():
    """Return a redis client; raises on connection failure."""
    import redis

    return redis.from_url("redis://localhost:6379/0", decode_responses=True)


def redis_setex(key: str, ttl: int, value: str) -> bool:
    """Store a string value in Redis with TTL. Returns True on success."""
    try:
        r = _get_redis()
        r.setex(key, ttl, value)
        return True
    except Exception as e:
        log(f"  ERROR: Redis setex({key}) failed: {e}")
        return False


# ── camoufox-cli helper ────────────────────────────────────────────────────────


def _cfx(session: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a camoufox-cli command for the given session name."""
    cmd = ["camoufox-cli", "--session", session, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def cfx_close(session: str) -> None:
    """Best-effort close of a camoufox session."""
    try:
        _cfx(session, "close", timeout=10)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Provider Balance Sync
# (MiniMax, Moonshot, Z.AI, DeepSeek, xAI)
# ══════════════════════════════════════════════════════════════════════════════

PROVIDERS = {
    "minimax": {
        "url": "https://platform.minimax.io/user-center/payment/balance",
        "total": 25.0,
    },
    "moonshot": {
        "url": "https://platform.moonshot.ai/console/account",
        "total": 25.0,
    },
    "zhipu": {
        "url": "https://z.ai/manage-apikey/billing",
        "total": 10.0,
    },
    "deepseek": {
        "url": "https://platform.deepseek.com/usage",
        "total": 12.0,
    },
    "xai": {
        "url": "https://console.x.ai/team/f0ca6117-e73f-4fec-b5ab-4391eb612200/billing",
        "total": 25.0,
    },
}


def scrape_providers() -> dict[str, str]:
    """Open each provider URL sequentially using the shared session.

    Returns a dict of provider_name → raw body text (or 'ERROR: ...' on failure).
    The session is opened/reused here and must be closed by the caller.
    """
    results: dict[str, str] = {}
    names = list(PROVIDERS.keys())

    try:
        # First provider: open with persistent profile (starts browser if not running)
        first_name, first_url = names[0], PROVIDERS[names[0]]["url"]
        open_r = _cfx(CFX_SESSION, "--persistent", "open", first_url, timeout=30)
        if open_r.returncode != 0:
            log(f"  ERROR: cfx open failed for {first_name}: {open_r.stderr[:200]}")
            return {}

        time.sleep(6)
        eval_r = _cfx(CFX_SESSION, "eval", "document.body.innerText.substring(0, 5000)", timeout=15)
        results[first_name] = (
            eval_r.stdout if eval_r.returncode == 0 else f"ERROR: {eval_r.stderr[:200]}"
        )
        log(f"  [{first_name}] scraped {len(results[first_name])} chars")

        # Remaining providers reuse the same browser session
        for name in names[1:]:
            url = PROVIDERS[name]["url"]
            _cfx(CFX_SESSION, "open", url, timeout=20)
            time.sleep(6)
            eval_r = _cfx(
                CFX_SESSION,
                "eval",
                "document.body.innerText.substring(0, 5000)",
                timeout=15,
            )
            results[name] = (
                eval_r.stdout if eval_r.returncode == 0 else f"ERROR: {eval_r.stderr[:200]}"
            )
            log(f"  [{name}] scraped {len(results.get(name, ''))} chars")

    except subprocess.TimeoutExpired:
        log("  ERROR: camoufox timeout during provider scrape")
    except Exception as e:
        log(f"  ERROR: provider scrape failed: {e}")

    return results


# ── Parsers ────────────────────────────────────────────────────────────────────


def parse_minimax(text: str) -> dict | None:
    """MiniMax: 'Current balance\n24.24' or '$24.24'."""
    if not text or "Sign in" in text:
        return None
    m = re.search(r"\$\s*([\d,]+\.?\d+)\s*\n\s*Current balance", text)
    if m:
        return {"remaining": float(m.group(1).replace(",", ""))}
    m = re.search(r"Current balance\s*\n\s*([\d,]+\.?\d+)", text)
    if m:
        return {"remaining": float(m.group(1).replace(",", ""))}
    m = re.search(r"\$\s*([\d,]+\.?\d+)", text)
    if m:
        val = float(m.group(1).replace(",", ""))
        if 0 < val < 10000:
            return {"remaining": val}
    return None


def parse_moonshot(text: str) -> dict | None:
    """Moonshot AI (Kimi): 'Balance ($)\n23.67811'."""
    if not text or "Sign in" in text:
        return None
    m = re.search(r"Balance\s*\(\$\)\s*\n?\s*([\d,]+\.?\d+)", text)
    if m:
        return {"remaining": float(m.group(1).replace(",", ""))}
    m = re.search(r"[Bb]alance[:\s]*\$?\s*([\d,]+\.?\d+)", text)
    if m:
        val = float(m.group(1).replace(",", ""))
        if 0 < val < 10000:
            return {"remaining": val}
    return None


def parse_zhipu(text: str) -> dict | None:
    """Z.AI (智譜): 'Cash balance\n$ 10.00'."""
    if not text or "Sign in" in text:
        return None
    m = re.search(r"\$\s*([\d,]+\.?\d+)\s*\n\s*Cash balance", text)
    if m:
        return {"remaining": float(m.group(1).replace(",", ""))}
    m = re.search(r"Cash balance\s*\n?\s*\$?\s*([\d,]+\.?\d+)", text)
    if m:
        return {"remaining": float(m.group(1).replace(",", ""))}
    m = re.search(r"\$\s*([\d,]+\.?\d+)", text)
    if m:
        val = float(m.group(1).replace(",", ""))
        if 0 < val < 10000:
            return {"remaining": val}
    return None


def parse_deepseek(text: str) -> dict | None:
    """DeepSeek: '充值余额\n$10.25\nUSD'."""
    if not text or "Sign in" in text or "登录" in text:
        return None
    m = re.search(r"充值[余餘][额額]\s*\n?\s*\$\s*([\d,]+\.?\d+)", text)
    if m:
        return {"remaining": float(m.group(1).replace(",", ""))}
    m = re.search(r"[Bb]alance\s*\n?\s*\$\s*([\d,]+\.?\d+)", text)
    if m:
        return {"remaining": float(m.group(1).replace(",", ""))}
    return None


def parse_xai(text: str) -> dict | None:
    """xAI: billing page — credit balance shown under 'Credits' section."""
    if not text or "Access to team denied" in text:
        return None
    m = re.search(
        r"Credits\s*\n\s*[^\n]*credit balance[^\n]*\n\s*\$\s*([\d,]+\.?\d+)", text, re.IGNORECASE
    )
    if m:
        return {"remaining": float(m.group(1).replace(",", ""))}
    # Legacy layout
    m_credits = re.search(r"Purchased credits[^$]*\$\s*([\d,]+\.?\d+)", text, re.DOTALL)
    m_free = re.search(r"Free credits[^$]*\$\s*([\d,]+\.?\d+)", text, re.DOTALL)
    m_spend = re.search(r"API spend\s*\n\s*\$\s*([\d,]+\.?\d+)", text)
    if m_credits:
        purchased = float(m_credits.group(1).replace(",", ""))
        free = float(m_free.group(1).replace(",", "")) if m_free else 0.0
        spend = float(m_spend.group(1).replace(",", "")) if m_spend else 0.0
        return {"remaining": round(purchased + free - spend, 4)}
    return None


PROVIDER_PARSERS = {
    "minimax": parse_minimax,
    "moonshot": parse_moonshot,
    "zhipu": parse_zhipu,
    "deepseek": parse_deepseek,
    "xai": parse_xai,
}


def store_provider_results(results: dict) -> int:
    """Store parsed provider results to Redis. Returns success count."""
    try:
        r = _get_redis()
    except Exception as e:
        log(f"  ERROR: Redis connection failed: {e}")
        return 0

    ok = 0
    for name, data in results.items():
        if data.get("status") == "ok":
            key = f"{REDIS_KEY_PREFIX}:{name}:balance"
            r.setex(key, REDIS_TTL, json.dumps(data))
            ok += 1

    r.setex(f"{REDIS_KEY_PREFIX}:all_balances", REDIS_TTL, json.dumps(results))
    return ok


def run_provider_sync() -> int:
    """Section 1: scrape + parse + store provider balances.

    Returns number of providers successfully stored.
    Session (CFX_SESSION) is LEFT OPEN for Section 3 (Google).
    """
    log("--- Section 1: Provider Balance Sync ---")
    raw_texts = scrape_providers()

    if not raw_texts:
        log("  ERROR: No data scraped from any provider")
        return 0

    raw_dir = LOG_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    results: dict = {}
    ts = datetime.now(UTC).isoformat()

    for name, cfg in PROVIDERS.items():
        text = raw_texts.get(name, "")
        if not text or text.startswith("ERROR:"):
            log(f"  [{name}] scrape error: {text[:100]}")
            results[name] = {"status": "scrape_failed", "total": cfg["total"], "synced_at": ts}
            continue

        (raw_dir / f"{name}_raw.txt").write_text(text)

        parsed = PROVIDER_PARSERS[name](text)
        if parsed and "remaining" in parsed:
            remaining = parsed["remaining"]
            results[name] = {
                "name": name,
                "total": cfg["total"],
                "remaining": remaining,
                "spent": round(cfg["total"] - remaining, 4),
                "source": "scraped",
                "synced_at": ts,
                "status": "ok",
            }
            log(f"  [{name}] OK: remaining=${remaining}")
        else:
            log(f"  [{name}] parse failed — raw saved to {raw_dir / f'{name}_raw.txt'}")
            results[name] = {"status": "parse_failed", "total": cfg["total"], "synced_at": ts}

    ok = store_provider_results(results)
    log(f"  Stored {ok}/{len(PROVIDERS)} providers to Redis")

    # Fallback JSON dump
    Path("/tmp/agent-metrics-provider-balances.json").write_text(json.dumps(results, indent=2))
    return ok


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: DashScope (Qwen) Free Quota Sync
# ══════════════════════════════════════════════════════════════════════════════

DASHSCOPE_URL = (
    "https://modelstudio.console.alibabacloud.com/ap-southeast-1/"
    "?tab=dashboard#/model-usage/free-quota"
)
DASHSCOPE_REDIS_KEY = "agent-metrics:dashscope:free_quota"


def _dashscope_auto_login() -> bool:
    """Auto-login to DashScope via Google OAuth (session cookies don't persist)."""
    try:
        # Click "立即登录"
        snap_r = _cfx(CFX_SESSION, "snapshot", "-i", timeout=10)
        if snap_r.returncode != 0:
            return False
        # Find the login button ref
        for line in snap_r.stdout.splitlines():
            if "立即登录" in line:
                ref_match = re.search(r"\[ref=(e\d+)\]", line)
                if ref_match:
                    _cfx(CFX_SESSION, "click", f"@{ref_match.group(1)}", timeout=10)
                    time.sleep(3)
                    break
        else:
            log("  WARN: 立即登录 button not found")
            return False

        # Click "使用Google帳號登入"
        snap_r2 = _cfx(CFX_SESSION, "snapshot", "-i", timeout=10)
        if snap_r2.returncode != 0:
            return False
        for line in snap_r2.stdout.splitlines():
            if "Google" in line and "登入" in line:
                ref_match = re.search(r"\[ref=(e\d+)\]", line)
                if ref_match:
                    _cfx(CFX_SESSION, "click", f"@{ref_match.group(1)}", timeout=10)
                    time.sleep(5)  # Wait for OAuth redirect
                    break
        else:
            log("  WARN: Google login button not found")
            return False

        # Verify login succeeded
        check_r = _cfx(
            CFX_SESSION,
            "eval",
            "document.body.innerText.includes('模型总数') || document.body.innerText.includes('免费额度使用概览')",
            timeout=10,
        )
        if check_r.returncode == 0 and "true" in check_r.stdout.lower():
            log("  Auto-login via Google OAuth succeeded")
            return True

        log("  WARN: Auto-login completed but page not ready, waiting more...")
        time.sleep(5)
        return True  # Optimistic — page may still be loading

    except Exception as e:
        log(f"  WARN: Auto-login failed: {e}")
        return False


def _scrape_dashscope_camoufox() -> str | None:
    """Primary scrape path: reuses shared camoufox session, auto-logins if needed."""
    try:
        open_r = _cfx(CFX_SESSION, "open", DASHSCOPE_URL, timeout=30)
        if open_r.returncode != 0:
            log(f"  ERROR: camoufox open failed: {open_r.stderr[:200]}")
            return None

        time.sleep(8)  # DashScope SPA initial render

        # Check if logged in
        check_r = _cfx(
            CFX_SESSION,
            "eval",
            "document.body.innerText.includes('登录以使用') ? 'need_login' : 'ok'",
            timeout=10,
        )
        if check_r.returncode == 0 and "need_login" in check_r.stdout:
            log("  DashScope session expired, auto-logging in via Google OAuth...")
            if not _dashscope_auto_login():
                log("  ERROR: Auto-login failed")
                return None
            # Re-navigate after login (OAuth may have changed the URL)
            _cfx(CFX_SESSION, "open", DASHSCOPE_URL, timeout=30)
            time.sleep(8)

        eval_r = _cfx(
            CFX_SESSION,
            "eval",
            "document.body.innerText.substring(0, 8000)",
            timeout=15,
        )
        if eval_r.returncode != 0:
            log(f"  ERROR: camoufox eval failed: {eval_r.stderr[:200]}")
            return None

        return eval_r.stdout.strip() or None

    except subprocess.TimeoutExpired:
        log("  ERROR: camoufox DashScope timeout")
        return None
    except FileNotFoundError:
        log("  WARN: camoufox-cli not found")
        return None
    except Exception as e:
        log(f"  ERROR: camoufox DashScope failed: {e}")
        return None
    # No cfx_close here — shared session, main() handles cleanup


def _scrape_dashscope_playwright() -> str | None:
    """Fallback scrape path: playwright-cli with APFS-cloned profile."""
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
        log(f"  ERROR: pw_session init failed: {init_result.stdout[:200]}")
        return None

    session_id = f"{sid}-dashscope"
    try:
        subprocess.run(
            ["playwright-cli", "--profile", profile_dir, f"-s={session_id}", "open", DASHSCOPE_URL],
            capture_output=True,
            text=True,
            timeout=30,
        )
        time.sleep(5)

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

        subprocess.run(
            ["playwright-cli", f"-s={session_id}", "close"], capture_output=True, timeout=10
        )
        subprocess.run(
            [str(PYTHON), str(PW_SESSION), "cleanup", profile_dir],
            capture_output=True,
            timeout=10,
        )

        if eval_result.returncode != 0:
            log(f"  ERROR: playwright eval failed: {eval_result.stderr[:200]}")
            return None

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
        log("  ERROR: playwright DashScope timeout")
        return None
    except Exception as e:
        log(f"  ERROR: playwright DashScope failed: {e}")
        return None
    finally:
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


def _scrape_dashscope_safari() -> str | None:
    """Last-resort fallback: Safari via osascript."""
    safari_exec = HOME / ".claude/scripts/safari_exec.py"
    if not safari_exec.exists():
        return None
    try:
        subprocess.run(
            [str(PYTHON), str(safari_exec), "nav", DASHSCOPE_URL],
            capture_output=True,
            text=True,
            timeout=15,
        )
        time.sleep(5)
        result = subprocess.run(
            [
                str(PYTHON),
                str(safari_exec),
                "eval",
                "document.body.innerText.substring(0, 8000)",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except Exception as e:
        log(f"  ERROR: safari fallback failed: {e}")
    return None


def parse_dashscope_quota(text: str) -> dict | None:
    """Parse DashScope free quota page (supports Chinese + English UI).

    Chinese: "95\\n模型总数", "剩999,961/共1,000,000"
    English: "95\\nTotal Number of Models", "Remaining 999,961 / Total 1,000,000"
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
            if (
                "模型总数" in next_line
                or "模型總數" in next_line
                or "Total Number of Models" in next_line
            ):
                try:
                    result["total_models"] = int(stripped.replace(",", ""))
                except ValueError:
                    pass
            elif (
                "额度充沛" in next_line
                or "額度充沛" in next_line
                or "Sufficient quota" in next_line
            ):
                try:
                    result["healthy"] = int(stripped.replace(",", ""))
                except ValueError:
                    pass
            elif "使用超50%" in next_line or "over 50% used" in next_line:
                try:
                    result["over_50pct"] = int(stripped.replace(",", ""))
                except ValueError:
                    pass
            elif "使用超80%" in next_line or "over 80% used" in next_line:
                try:
                    result["over_80pct"] = int(stripped.replace(",", ""))
                except ValueError:
                    pass
            elif (
                "无免费额度" in next_line
                or "無免費額度" in next_line
                or "no free quota" in next_line
            ):
                try:
                    result["no_free"] = int(stripped.replace(",", ""))
                except ValueError:
                    pass

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
                    {"model": model_name, "remaining": remaining, "total": total}
                )

    return result if result["total_models"] > 0 else None


def run_dashscope_sync() -> bool:
    """Section 2: scrape + parse + store DashScope free quota.

    Returns True on success.
    """
    log("--- Section 2: DashScope Quota Sync ---")

    text = _scrape_dashscope_camoufox()
    if not text:
        log("  Camoufox failed, trying Playwright CLI...")
        text = _scrape_dashscope_playwright()
    if not text:
        log("  Playwright failed, trying Safari...")
        text = _scrape_dashscope_safari()

    if not text:
        log("  ERROR: All DashScope scrape methods failed")
        return False

    log(f"  Scraped {len(text)} chars")

    data = parse_dashscope_quota(text)
    if not data:
        log("  ERROR: Failed to parse DashScope quota data")
        log(f"  Text preview: {text[:300]}")
        return False

    log(
        f"  Parsed: {data['total_models']} models, {data['healthy']} healthy, "
        f"{len(data['top_models'])} top models"
    )

    if redis_setex(DASHSCOPE_REDIS_KEY, REDIS_TTL, json.dumps(data)):
        log(f"  Stored to Redis ({DASHSCOPE_REDIS_KEY}, TTL={REDIS_TTL}s)")
    else:
        fallback = Path("/tmp/agent-metrics-qwen-quota.json")
        fallback.write_text(json.dumps(data))
        log(f"  Redis failed, wrote to {fallback}")

    return True


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Google Developer Program Credits Sync (NEW)
# ══════════════════════════════════════════════════════════════════════════════

GOOGLE_BILLING_URL = "https://console.cloud.google.com/billing/credits?hl=zh-tw"
GOOGLE_REDIS_KEY = f"{REDIS_KEY_PREFIX}:google"

# Credit names to look for (partial match, case-insensitive)
GOOGLE_CREDIT_PATTERN = re.compile(r"google developer program premium benefit", re.IGNORECASE)


def _scrape_google_credits_camoufox() -> str | None:
    """Scrape Google Cloud billing credits page.

    Reuses the shared providers session (CFX_SESSION) — same browser
    instance that was used for provider scrapes is still open.
    """
    try:
        # Navigate to billing credits page in the already-open session
        open_r = _cfx(CFX_SESSION, "open", GOOGLE_BILLING_URL, timeout=30)
        if open_r.returncode != 0:
            log(f"  ERROR: cfx open (google) failed: {open_r.stderr[:200]}")
            # Try opening fresh with persistent flag as recovery
            open_r = _cfx(CFX_SESSION, "--persistent", "open", GOOGLE_BILLING_URL, timeout=30)
            if open_r.returncode != 0:
                return None

        # Google Cloud Console is a heavy SPA — give it extra time
        time.sleep(8)

        # Try to extract the credits table text
        eval_r = _cfx(
            CFX_SESSION,
            "eval",
            "document.body.innerText.substring(0, 10000)",
            timeout=20,
        )
        if eval_r.returncode != 0:
            log(f"  ERROR: cfx eval (google) failed: {eval_r.stderr[:200]}")
            return None

        return eval_r.stdout.strip() or None

    except subprocess.TimeoutExpired:
        log("  ERROR: camoufox Google credits timeout")
        return None
    except Exception as e:
        log(f"  ERROR: camoufox Google credits failed: {e}")
        return None


def parse_google_credits(text: str) -> dict | None:
    """Parse Google Cloud billing credits page text.

    Looks for rows matching 'Google Developer Program premium benefit'.
    Expected line patterns (zh-tw UI):
      - Credit name
      - Status (有效 / 到期 / active / expired)
      - Remaining percentage (e.g. "99%")
      - Remaining amount (e.g. "$320.00")
      - Original amount (e.g. "$321.72")
      - Type (e.g. "Promotional")

    Two credit objects expected → stored individually + sum.
    Fallback: grab any USD amounts near the pattern keywords.
    """
    if not text or len(text) < 50:
        return None

    lines = [l.strip() for l in text.split("\n")]
    ts = datetime.now(UTC).isoformat()

    credits_found: list[dict] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        if GOOGLE_CREDIT_PATTERN.search(line):
            # Found a credit row — try to parse surrounding lines
            credit: dict = {
                "name": line,
                "status": None,
                "remaining_pct": None,
                "remaining_usd": None,
                "original_usd": None,
                "type": None,
            }

            # Look at next ~8 lines for the fields
            window = lines[i + 1 : i + 9]
            for j, wline in enumerate(window):
                # Status: Chinese (有效/到期) or English (Active/Expired)
                if re.match(r"^(有效|到期|[Aa]ctive|[Ee]xpired)$", wline):
                    credit["status"] = wline

                # Remaining percentage: "99%" or "99.5%"
                m_pct = re.match(r"^(\d+(?:\.\d+)?)\s*%$", wline)
                if m_pct:
                    credit["remaining_pct"] = float(m_pct.group(1))

                # USD amounts: "$320.00" or "USD320.00" or "US$320.00"
                m_usd = re.match(r"^(?:US)?\$\s*([\d,]+\.?\d*)$", wline)
                if not m_usd:
                    m_usd = re.match(r"^USD\s*([\d,]+\.?\d*)$", wline)
                if m_usd:
                    val = float(m_usd.group(1).replace(",", ""))
                    if credit["remaining_usd"] is None:
                        credit["remaining_usd"] = val
                    elif credit["original_usd"] is None:
                        credit["original_usd"] = val

                # Type: Promotional / GCP credits etc.
                if re.match(r"^(Promotional|GCP|Free|Trial|Developer)", wline, re.IGNORECASE):
                    credit["type"] = wline

            # Only keep if we found at least a USD amount
            if credit["remaining_usd"] is not None:
                credits_found.append(credit)
                log(
                    f"  [google] Credit: {credit['name'][:50]} | "
                    f"remaining=${credit['remaining_usd']} | "
                    f"status={credit['status']}"
                )

        i += 1

    # Fallback: if no structured match, do broad USD extraction near keyword
    if not credits_found:
        # Find all USD-like amounts in the page as a last resort
        all_amounts = re.findall(r"\$\s*([\d,]+\.?\d+)", text)
        if all_amounts:
            log(f"  [google] Fallback: found USD amounts: {all_amounts[:10]}")
            # Can't confidently assign without structure — store raw
            return {
                "status": "parse_partial",
                "raw_amounts_usd": [float(a.replace(",", "")) for a in all_amounts[:10]],
                "credits": [],
                "total_remaining_usd": None,
                "synced_at": ts,
                "source": "scraped_fallback",
            }

    if not credits_found:
        return None

    # Sum all remaining amounts
    total_remaining = round(
        sum(c["remaining_usd"] for c in credits_found if c["remaining_usd"] is not None), 2
    )

    return {
        "status": "ok",
        "credits": credits_found,
        "total_remaining_usd": total_remaining,
        "count": len(credits_found),
        "synced_at": ts,
        "source": "scraped",
    }


def run_google_sync() -> bool:
    """Section 3: scrape + parse + store Google Developer Program credits.

    Returns True on success.
    The shared provider session (CFX_SESSION) must still be active.
    """
    log("--- Section 3: Google Developer Credits Sync ---")

    text = _scrape_google_credits_camoufox()

    if not text:
        log("  ERROR: Failed to scrape Google billing credits")
        return False

    log(f"  Scraped {len(text)} chars")

    # Save raw for debugging
    raw_dir = LOG_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "google_raw.txt").write_text(text)

    data = parse_google_credits(text)
    if not data:
        log("  ERROR: Failed to parse Google credits — raw saved to logs/raw/google_raw.txt")
        log(f"  Text preview: {text[:400]}")
        return False

    if data.get("status") == "ok":
        log(f"  Parsed: {data['count']} credit(s), total remaining=${data['total_remaining_usd']}")
    else:
        log(f"  Parsed (partial): {data}")

    if redis_setex(GOOGLE_REDIS_KEY, REDIS_TTL, json.dumps(data)):
        log(f"  Stored to Redis ({GOOGLE_REDIS_KEY}, TTL={REDIS_TTL}s)")
    else:
        fallback = Path("/tmp/agent-metrics-google-credits.json")
        fallback.write_text(json.dumps(data))
        log(f"  Redis failed, wrote to {fallback}")

    return True


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════


def main() -> int:
    log("=" * 60)
    log("ws-credits-sync: Unified LLM credits & quota sync")
    log("=" * 60)

    results: dict[str, bool | int] = {}

    try:
        # Section 1: Provider balances (opens CFX_SESSION, leaves it open)
        ok_count = run_provider_sync()
        results["provider"] = ok_count > 0

        # Section 2: DashScope quota (reuses shared session)
        results["dashscope"] = run_dashscope_sync()

        # Section 3: Google credits (reuses shared session)
        results["google"] = run_google_sync()

    finally:
        # Close the single shared session
        log("  Closing camoufox session...")
        cfx_close(CFX_SESSION)

    # ── Summary ────────────────────────────────────────────────────────────────
    log("-" * 60)
    for name, ok in results.items():
        status = "OK" if ok else "FAIL"
        log(f"  {name}: {status}")

    failures = sum(1 for v in results.values() if not v)
    if failures:
        log(f"WARN: {failures} section(s) failed")
    else:
        log("All sections completed successfully")
    log("=" * 60)

    return 0 if failures == 0 else 1


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

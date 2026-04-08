#!/usr/bin/env python3
"""
ws_provider_balance_sync.py — Sync LLM provider balances via camoufox-cli

Scrapes balance/usage dashboards for MiniMax, Moonshot, Z.AI, DeepSeek, xAI.
Uses camoufox-cli with persistent Firefox profile (anti-detect, cookies maintained by user).

Stores results in Redis for agent-metrics consumption.

Logs: ~/workshop/outputs/scheduler/logs/ws-provider-balance-sync.log
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
LOG_DIR = HOME / "workshop/outputs/scheduler/logs"
LOG_FILE = LOG_DIR / "ws-provider-balance-sync.log"
REDIS_KEY_PREFIX = "agent-metrics:provider"
REDIS_TTL = 86400 * 7  # 7 days
CFX_SESSION = "balance-sync"

os.environ["PATH"] = (
    f"/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:"
    f"/usr/sbin:/sbin:{HOME}/.local/bin:{os.environ.get('PATH', '')}"
)

# ── Provider definitions ───────────────────────────────────────
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
    "google": {
        "url": "https://console.cloud.google.com/billing/credits?hl=zh-tw",
        "total": 635.0,
    },
}


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── camoufox-cli helpers ──────────────────────────────────────


def _cfx(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a camoufox-cli command with the sync session."""
    cmd = ["camoufox-cli", "--session", CFX_SESSION, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def scrape_all_providers() -> dict[str, str]:
    """Open each provider URL sequentially, extract body text."""
    results: dict[str, str] = {}

    try:
        # Open first provider to start browser with persistent profile
        first_name = list(PROVIDERS.keys())[0]
        first_url = PROVIDERS[first_name]["url"]

        open_r = _cfx("--persistent", "open", first_url)
        if open_r.returncode != 0:
            log(f"ERROR: cfx open failed: {open_r.stderr[:200]}")
            return {}

        # Wait for SPA to render
        time.sleep(6)

        # Extract text from first provider
        eval_r = _cfx("eval", "document.body.innerText.substring(0, 5000)", timeout=15)
        results[first_name] = (
            eval_r.stdout if eval_r.returncode == 0 else f"ERROR: {eval_r.stderr[:200]}"
        )
        log(f"  [{first_name}] scraped {len(results[first_name])} chars")

        # Scrape remaining providers sequentially
        for name, cfg in list(PROVIDERS.items())[1:]:
            _cfx("open", cfg["url"], timeout=20)
            time.sleep(6)

            eval_r = _cfx("eval", "document.body.innerText.substring(0, 5000)", timeout=15)
            if eval_r.returncode == 0:
                results[name] = eval_r.stdout
            else:
                results[name] = f"ERROR: {eval_r.stderr[:200]}"
            log(f"  [{name}] scraped {len(results.get(name, ''))} chars")

    except subprocess.TimeoutExpired:
        log("ERROR: camoufox timeout")
    except Exception as e:
        log(f"ERROR: camoufox failed: {e}")
    finally:
        try:
            _cfx("close", timeout=10)
        except Exception:
            pass

    return results


# ── Parsers (based on real scraping 2026-03-13) ────────────────


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
    """DeepSeek: '充值余额 \n$10.25\nUSD'."""
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
    # New layout (2026-04): Credits section shows '$24.82' followed by 'Purchase credits'
    m = re.search(
        r"Credits\s*\n\s*[^\n]*credit balance[^\n]*\n\s*\$\s*([\d,]+\.?\d+)", text, re.IGNORECASE
    )
    if m:
        return {"remaining": float(m.group(1).replace(",", ""))}
    # Legacy layout: 'Purchased credits' + 'API spend'
    m_credits = re.search(r"Purchased credits[^$]*\$\s*([\d,]+\.?\d+)", text, re.DOTALL)
    m_free = re.search(r"Free credits[^$]*\$\s*([\d,]+\.?\d+)", text, re.DOTALL)
    m_spend = re.search(r"API spend\s*\n\s*\$\s*([\d,]+\.?\d+)", text)
    if m_credits:
        purchased = float(m_credits.group(1).replace(",", ""))
        free = float(m_free.group(1).replace(",", "")) if m_free else 0.0
        spend = float(m_spend.group(1).replace(",", "")) if m_spend else 0.0
        return {"remaining": round(purchased + free - spend, 4)}
    return None


def parse_google(text: str) -> dict | None:
    """Google Cloud: billing credits — table with '剩餘的抵免額' column (2x CREDIT_TYPE_MONTHLY)."""
    if not text or "Sign in" in text:
        return None
    # Sum all dollar amounts in '剩餘的抵免額' column
    remaining_matches = re.findall(r"\$\s*([\d,]+\.?\d+)", text)
    original_matches = re.findall(r"原始值", text)
    if remaining_matches and original_matches:
        # Table has pairs: remaining + original per row; extract remaining values
        vals = [float(v.replace(",", "")) for v in remaining_matches]
        # Filter for credit-range amounts (> $50)
        credits = [v for v in vals if 50 < v < 1000]
        if credits:
            return {"remaining": round(sum(credits), 2)}
    # Fallback: '剩餘' near dollar
    m = re.search(r"剩餘[^\$]*\$\s*([\d,]+\.?\d+)", text)
    if m:
        return {"remaining": float(m.group(1).replace(",", ""))}
    return None


PARSERS = {
    "minimax": parse_minimax,
    "moonshot": parse_moonshot,
    "zhipu": parse_zhipu,
    "deepseek": parse_deepseek,
    "xai": parse_xai,
    "google": parse_google,
}


# ── Redis ──────────────────────────────────────────────────────


def store_results(results: dict) -> int:
    """Store parsed results to Redis. Returns success count."""
    try:
        import redis

        r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
    except Exception as e:
        log(f"ERROR: Redis connection failed: {e}")
        return 0

    ok = 0
    for name, data in results.items():
        if data.get("status") == "ok":
            key = f"{REDIS_KEY_PREFIX}:{name}:balance"
            r.setex(key, REDIS_TTL, json.dumps(data))
            ok += 1

    # Combined summary
    r.setex(f"{REDIS_KEY_PREFIX}:all_balances", REDIS_TTL, json.dumps(results))
    return ok


# ── Main ───────────────────────────────────────────────────────


def main() -> int:
    log("=== Provider Balance Sync Start (camoufox) ===")

    raw_texts = scrape_all_providers()

    if not raw_texts:
        log("ERROR: No data scraped from any provider")
        return 1

    # Save raw texts for debugging
    raw_dir = LOG_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    ts = datetime.now(UTC).isoformat()

    for name, cfg in PROVIDERS.items():
        text = raw_texts.get(name, "")
        if text.startswith("ERROR:"):
            log(f"  [{name}] scrape error: {text}")
            results[name] = {"status": "scrape_failed", "total": cfg["total"], "synced_at": ts}
            continue

        (raw_dir / f"{name}_raw.txt").write_text(text)

        parser = PARSERS[name]
        parsed = parser(text)

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

    ok = store_results(results)
    log(f"Stored {ok}/{len(PROVIDERS)} to Redis")

    # Fallback JSON
    Path("/tmp/agent-metrics-provider-balances.json").write_text(json.dumps(results, indent=2))

    log(f"=== Provider Balance Sync Done: {ok}/{len(PROVIDERS)} OK ===")
    return 0 if ok > 0 else 1


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

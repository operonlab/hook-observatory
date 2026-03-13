#!/usr/bin/env python3
"""
ws_provider_balance_sync.py — Sync LLM provider balances via Playwright CLI

Scrapes balance/usage dashboards for MiniMax, Moonshot, Z.AI, DeepSeek, xAI.
All use Google OAuth — single Playwright session, multi-tab scraping.

Stores results in Redis for agent-metrics consumption.

Logs: ~/workshop/outputs/scheduler/logs/ws-provider-balance-sync.log
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
LOG_FILE = LOG_DIR / "ws-provider-balance-sync.log"
REDIS_KEY_PREFIX = "agent-metrics:provider"
REDIS_TTL = 86400 * 7  # 7 days

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
}


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── Playwright helpers ─────────────────────────────────────────


def init_session() -> tuple[str, str] | None:
    """Init Playwright session (APFS clone of master profile)."""
    result = subprocess.run(
        [str(PYTHON), str(PW_SESSION), "init"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    profile_dir = sid = None
    for line in result.stdout.splitlines():
        if line.startswith("export PW_PROFILE="):
            profile_dir = line.split("=", 1)[1].strip().strip("'\"")
        elif line.startswith("export SID="):
            sid = line.split("=", 1)[1].strip().strip("'\"")
    if not profile_dir or not sid:
        log(f"ERROR: pw_session init failed: {result.stdout[:200]}")
        return None
    return profile_dir, sid


def scrape_all_providers(profile_dir: str, sid: str) -> dict[str, str]:
    """Open all provider URLs and extract text via single session + run-code."""
    session_id = f"{sid}-balance"
    urls = {name: cfg["url"] for name, cfg in PROVIDERS.items()}
    provider_names = list(urls.keys())
    provider_urls = list(urls.values())

    # Build JS that opens all URLs as tabs, waits, then extracts text from each
    js_code = f"""async (page) => {{
      const urls = {json.dumps(provider_urls)};
      const names = {json.dumps(provider_names)};
      const results = {{}};

      // Open all URLs as new tabs
      const context = page.context();
      const tabs = [];
      for (const url of urls) {{
        const tab = await context.newPage();
        await tab.goto(url, {{ waitUntil: 'domcontentloaded', timeout: 20000 }}).catch(() => {{}});
        tabs.push(tab);
      }}

      // Wait for SPAs to render
      await page.waitForTimeout(6000);

      // Extract text from each tab
      for (let i = 0; i < tabs.length; i++) {{
        try {{
          const text = await tabs[i].evaluate(() => document.body.innerText.substring(0, 5000));
          results[names[i]] = text;
        }} catch (e) {{
          results[names[i]] = 'ERROR: ' + e.message;
        }}
      }}

      return JSON.stringify(results);
    }}"""

    try:
        # Open a blank page to start the browser
        open_r = subprocess.run(
            [
                "npx",
                "@playwright/cli",
                "--profile",
                profile_dir,
                f"-s={session_id}",
                "open",
                "about:blank",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if open_r.returncode != 0:
            log(f"ERROR: open failed: {open_r.stderr[:200]}")
            return {}

        # Run multi-tab scraping
        run_r = subprocess.run(
            [
                "npx",
                "@playwright/cli",
                f"-s={session_id}",
                "run-code",
                js_code,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if run_r.returncode != 0:
            log(f"ERROR: run-code failed: {run_r.stderr[:300]}")
            return {}

        # Parse result — look for JSON in output
        for line in run_r.stdout.split("\n"):
            stripped = line.strip()
            if stripped.startswith('"') and stripped.endswith('"'):
                try:
                    decoded = json.loads(stripped)
                    if isinstance(decoded, str):
                        return json.loads(decoded)
                except (json.JSONDecodeError, ValueError):
                    pass
            elif stripped.startswith("{"):
                try:
                    return json.loads(stripped)
                except (json.JSONDecodeError, ValueError):
                    pass

        log(f"ERROR: could not parse run-code output: {run_r.stdout[:300]}")
        return {}

    except subprocess.TimeoutExpired:
        log("ERROR: playwright timeout")
        return {}
    except Exception as e:
        log(f"ERROR: playwright failed: {e}")
        return {}
    finally:
        try:
            subprocess.run(
                ["npx", "@playwright/cli", f"-s={session_id}", "close"],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass


def cleanup_session(profile_dir: str) -> None:
    try:
        subprocess.run(
            [str(PYTHON), str(PW_SESSION), "cleanup", profile_dir],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass


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
    """xAI: billing page — 'Purchased credits\n...\n$25.00' + 'API spend\n$0.00'."""
    if not text or "Access to team denied" in text:
        return None
    # Purchased credits (total deposited)
    m_credits = re.search(r"Purchased credits[^$]*\$\s*([\d,]+\.?\d+)", text, re.DOTALL)
    # Free credits
    m_free = re.search(r"Free credits[^$]*\$\s*([\d,]+\.?\d+)", text, re.DOTALL)
    # API spend this month
    m_spend = re.search(r"API spend\s*\n\s*\$\s*([\d,]+\.?\d+)", text)
    if m_credits:
        purchased = float(m_credits.group(1).replace(",", ""))
        free = float(m_free.group(1).replace(",", "")) if m_free else 0.0
        spend = float(m_spend.group(1).replace(",", "")) if m_spend else 0.0
        remaining = purchased + free - spend
        return {"remaining": round(remaining, 4)}
    return None


PARSERS = {
    "minimax": parse_minimax,
    "moonshot": parse_moonshot,
    "zhipu": parse_zhipu,
    "deepseek": parse_deepseek,
    "xai": parse_xai,
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
    log("=== Provider Balance Sync Start ===")

    session = init_session()
    if not session:
        log("ERROR: Failed to init Playwright session")
        return 1

    profile_dir, sid = session
    log(f"Session: profile={profile_dir}, sid={sid}")

    raw_texts = scrape_all_providers(profile_dir, sid)
    cleanup_session(profile_dir)

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
        log(f"  [{name}] scraped {len(text)} chars")

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

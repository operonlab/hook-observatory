#!/usr/bin/env python3
"""
ws_finance_billing.py — Daily 6AM: process subscription + installment billing

Calls POST /api/finance/billing/process to:
1. Find active subscriptions where next_billing <= today → create expense transactions
2. Find scheduled installment transactions where transacted_at <= now → mark completed

Idempotent: safe to re-run (invoice_number dedup + status guards).

Logs: ~/workshop/outputs/finance/logs/billing.log
"""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home()
LOG_DIR = HOME / "workshop" / "outputs" / "finance" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "billing.log"

CORE_URL = os.getenv("CORE_URL", "http://127.0.0.1:8801")
ADMIN_COOKIE = os.getenv("WORKSHOP_ADMIN_COOKIE", "")


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def process_billing() -> dict:
    url = f"{CORE_URL}/api/finance/billing/process?space_id=default"
    req = urllib.request.Request(url, method="POST", data=b"")
    req.add_header("Content-Type", "application/json")
    if ADMIN_COOKIE:
        req.add_header("Cookie", f"workshop_session={ADMIN_COOKIE}")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode()[:200]}
    except Exception as e:
        return {"error": str(e)}


def main() -> None:
    log("Starting finance billing process...")
    result = process_billing()
    if "error" in result:
        log(f"FAILED: {result}")
    else:
        subs = result.get("subscriptions_processed", 0)
        inst = result.get("installments_processed", 0)
        log(
            f"OK: {subs} subscriptions billed, {inst} installments completed (total: {subs + inst})"
        )


if __name__ == "__main__":
    import fcntl
    import sys

    _lock_path = f"/tmp/{Path(__file__).stem}.lock"
    _lock_fd = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] Another instance already running (lock: {_lock_path})")
        sys.exit(0)
    main()

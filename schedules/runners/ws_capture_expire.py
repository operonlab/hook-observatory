#!/usr/bin/env python3
"""
ws_capture_expire.py — Daily 3AM: expire stale captures

Calls POST /api/captures/expire-stale to mark captures
past their expires_at as 'expired'.

Logs: ~/workshop/outputs/capture/logs/expire.log
"""

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home()
LOG_DIR = HOME / "workshop" / "outputs" / "capture" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "expire.log"

CORE_URL = os.getenv("CORE_URL", "http://127.0.0.1:8801")
# Admin cookie for scheduled tasks
ADMIN_COOKIE = os.getenv("WORKSHOP_ADMIN_COOKIE", "")


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def expire_stale() -> dict:
    url = f"{CORE_URL}/api/captures/expire-stale"
    req = urllib.request.Request(url, method="POST", data=b"")
    req.add_header("Content-Type", "application/json")
    if ADMIN_COOKIE:
        req.add_header("Cookie", f"workshop_session={ADMIN_COOKIE}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "body": e.read().decode()[:200]}
    except Exception as e:
        return {"error": str(e)}


def main() -> None:
    log("Starting capture expire_stale...")
    result = expire_stale()
    if "error" in result:
        log(f"FAILED: {result}")
    else:
        log(f"OK: expired {result.get('expired', 0)} captures")


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

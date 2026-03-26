#!/usr/bin/env python3
"""
ws_memvault_decay.py — Weekly Sunday 4AM confidence decay

Calls POST /api/memvault/kg/decay?space_id=default to apply
exponential half-life decay to all AttitudeFact confidence values.

Logs: ~/workshop/outputs/memvault/logs/decay.log
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Configuration ───────────────────────────────────────────────
HOME = Path.home()
LOG_DIR = HOME / "workshop/outputs/memvault/logs"
LOG_FILE = LOG_DIR / "decay.log"
CORE_API = "http://localhost:10000/api/memvault"
SPACE_ID = "default"


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[decay] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def api_post(url: str) -> tuple[int | None, dict | None]:
    """POST with empty body; returns (status_code, response_json)."""
    try:
        req = urllib.request.Request(  # noqa: S310
            url,
            data=b"",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            status = resp.status
            body = json.loads(resp.read())
            return status, body
    except urllib.error.HTTPError as e:
        log(f"HTTP error {e.code}: {e.reason}")
        return e.code, None
    except Exception as e:
        log(f"Request failed: {e}")
        return None, None


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log("========== Confidence decay started ==========")

    url = f"{CORE_API}/kg/decay?space_id={SPACE_ID}"
    log(f"POST {url}")

    status, body = api_post(url)

    if status == 200 and body is not None:
        checked = body.get("attitudes_checked", 0)
        updated = body.get("attitudes_updated", 0)
        log(f"OK: attitudes_checked={checked} attitudes_updated={updated}")
    else:
        log(f"FAILED: status={status} body={body}")
        sys.exit(1)

    log("========== Confidence decay complete ==========")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lib.process_lock import acquire_or_exit

    acquire_or_exit()
    main()

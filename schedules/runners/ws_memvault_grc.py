#!/usr/bin/env python3
"""
ws_memvault_grc.py — Weekly memvault G-R-C: reflect + curate

Calls POST /api/memvault/reflect then POST /api/memvault/curate
to analyze memory quality and archive low-value blocks.

Logs: ~/workshop/outputs/memvault/logs/grc.log
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Configuration ───────────────────────────────────────────────
HOME = Path.home()
LOG_DIR = HOME / "workshop/outputs/memvault/logs"
LOG_FILE = LOG_DIR / "grc.log"
CORE_API = "http://localhost:10000/api/memvault"
SPACE_ID = "default"
DRY_RUN = False
INTERNAL_KEY = os.environ.get("CORE_INTERNAL_API_KEY", "")


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[memvault-grc] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def api_post(url: str) -> tuple[int | None, dict | None]:
    """POST with empty body; returns (status_code, response_json)."""
    try:
        headers = {"Content-Type": "application/json"}
        if INTERNAL_KEY:
            headers["x-internal-key"] = INTERNAL_KEY
        req = urllib.request.Request(  # noqa: S310
            url,
            data=b"",
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            status = resp.status
            body = json.loads(resp.read())
            return status, body
    except urllib.error.HTTPError as e:
        log(f"HTTP error {e.code}: {e.reason}")
        return e.code, None
    except Exception as e:
        log(f"Request failed: {e}")
        return None, None


def run_stage(stage: str, extra_params: str = "") -> bool:
    url = f"{CORE_API}/{stage}?scope_id={SPACE_ID}{extra_params}"
    log(f"POST {url}")
    status, body = api_post(url)
    if status == 200 and body is not None:
        log(f"{stage} OK: {json.dumps(body, ensure_ascii=False)[:300]}")
        return True
    log(f"{stage} FAILED: status={status}")
    return False


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log("========== memvault G-R-C started ==========")

    dry_param = "&dry_run=true" if DRY_RUN else ""

    ok_reflect = run_stage("reflect")
    ok_curate = run_stage("curate", extra_params=dry_param)

    if ok_reflect and ok_curate:
        log("========== memvault G-R-C complete ==========")
    else:
        log("========== memvault G-R-C completed with errors ==========")
        sys.exit(1)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lib.process_lock import acquire_or_exit

    acquire_or_exit()
    main()

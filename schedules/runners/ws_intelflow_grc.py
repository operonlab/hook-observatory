#!/usr/bin/env python3
"""
ws_intelflow_grc.py — Weekly intelflow G-R-C: reflect + curate

Calls POST /api/intelflow/reflect then POST /api/intelflow/curate
to analyze feed quality and archive low-value reports.

Logs: ~/workshop/outputs/intelflow/logs/grc.log
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Configuration ───────────────────────────────────────────────
HOME = Path.home()
LOG_DIR = HOME / "workshop/outputs/intelflow/logs"
LOG_FILE = LOG_DIR / "grc.log"
CORE_API = "http://localhost:8801/api/intelflow"
SPACE_ID = "default"
DRY_RUN = False


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[intelflow-grc] {timestamp} {msg}"
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
    log("========== intelflow G-R-C started ==========")

    dry_param = "&dry_run=true" if DRY_RUN else ""

    ok_reflect = run_stage("reflect")
    ok_curate = run_stage("curate", extra_params=dry_param)

    if ok_reflect and ok_curate:
        log("========== intelflow G-R-C complete ==========")
    else:
        log("========== intelflow G-R-C completed with errors ==========")
        sys.exit(1)


if __name__ == "__main__":
    import fcntl

    _lock_path = f"/tmp/{Path(__file__).stem}.lock"  # noqa: S108
    _lock_fd = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] Another instance already running (lock: {_lock_path})")
        sys.exit(0)
    main()

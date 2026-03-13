#!/usr/bin/env python3
"""
ws_cannibalization_drift.py — Weekly cannibalization upstream drift check

Pipeline:
  1. Run cannibalization_drift.py --notify
  2. Rotate old logs (keep last 12)

Logs: ~/workshop/outputs/scheduler/logs/ws-cannibalization-drift.log
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
PYTHON = HOME / ".local/bin/python3"
SCRIPT = HOME / "workshop/scripts/cannibalization_drift.py"
LOG_DIR = HOME / "workshop/outputs/scheduler/logs"
LOG_FILE = LOG_DIR / "ws-cannibalization-drift.log"

# Extend PATH
os.environ["PATH"] = (
    f"/opt/homebrew/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:"
    + os.environ.get("PATH", "")
)


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[cannibalization] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log("========== Cannibalization drift check started ==========")

    cmd = [str(PYTHON), str(SCRIPT), "--notify"]
    with open(LOG_FILE, "a") as f:
        result = subprocess.run(cmd, stdout=f, stderr=f)

    if result.returncode == 0:
        log("Drift check completed successfully")
    else:
        log(f"Drift check failed with exit code {result.returncode}")
        sys.exit(1)

    log("========== Cannibalization drift check complete ==========")


if __name__ == "__main__":
    import fcntl

    _lock_path = f"/tmp/{Path(__file__).stem}.lock"
    _lock_fd = open(_lock_path, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"[SKIP] Another instance already running (lock: {_lock_path})")
        sys.exit(0)
    main()

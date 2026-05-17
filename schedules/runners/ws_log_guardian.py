#!/usr/bin/env python3
"""ws_log_guardian.py — Merged log scanning watchdog.

Replaces two 5-minute jobs (``ws-nginx-autoban`` + ``ws-cronicle-fail-alert``)
that each polled a different log source on the same cadence. Both
original scripts live in ``~/workshop/scripts/`` as standalone Python
files; we shell out to them in parallel so they keep their own isolated
runtime (one's failure can't poison the other) while sharing a single
cron slot.

Sub-scripts:
  - nginx_autoban.py     — scans nginx access.log for abusive IPs and
                            adds them to the ban list.
  - cronicle_fail_alert.py — checks Cronicle for failed jobs and notifies.

Exit code: worst of the two subprocess returncodes (0 if both succeed).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PY = Path.home() / ".local/bin/python3"
SCRIPTS_DIR = Path.home() / "workshop/scripts"
SUB_SCRIPTS = [
    SCRIPTS_DIR / "nginx_autoban.py",
    SCRIPTS_DIR / "cronicle_fail_alert.py",
]

LOG_FILE = Path.home() / "workshop/outputs/scheduler/logs/ws-log-guardian.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

PER_SCRIPT_TIMEOUT_S = 120


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001,S110 — log write is best-effort
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="log planned subprocesses without launching"
    )
    args = parser.parse_args()

    _log("=== ws-log-guardian start ===")

    # Launch both in parallel; they don't share state, just a tick.
    procs: list[tuple[Path, subprocess.Popen | None]] = []
    for script in SUB_SCRIPTS:
        if not script.is_file():
            _log(f"  SKIP {script.name}: file not found")
            procs.append((script, None))
            continue
        _log(f"  spawn {script.name} (dry_run={args.dry_run})")
        if args.dry_run:
            procs.append((script, None))
            continue
        p = subprocess.Popen([str(PY), str(script)])
        procs.append((script, p))

    worst_rc = 0
    for script, p in procs:
        if p is None:
            continue
        try:
            rc = p.wait(timeout=PER_SCRIPT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _log(f"  TIMEOUT {script.name} after {PER_SCRIPT_TIMEOUT_S}s, killing")
            p.kill()
            rc = 124
        _log(f"  done {script.name} rc={rc}")
        if rc != 0 and worst_rc == 0:
            worst_rc = rc

    _log(f"=== ws-log-guardian done worst_rc={worst_rc} ===")
    return worst_rc


if __name__ == "__main__":
    sys.exit(main())

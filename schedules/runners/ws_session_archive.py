#!/usr/bin/env python3
"""
ws_session_archive.py — Daily 5:15AM session lifecycle pipeline

Pipeline (sequential, fail-safe):
  1. redact sweep — catch any sessions missed by SessionEnd hook
  2. scan         — discover all sessions, update DB index
  3. archive      — compress cold candidates with summaries + embeddings

Design: 3-layer fallback strategy
  Layer 1 (real-time): SessionEnd hook → pipeline (redact → extract → archive → log)
  Layer 2 (daily):     This script — sweep redact + scan + archive (catches hook failures)
  Layer 3 (manual):    SDK / CLI available anytime

Logs: ~/.claude/data/session-archiver/run.log
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
HOME = Path.home()
STATION_DIR = HOME / "workshop/stations/session-archiver"
LOG_DIR = HOME / ".claude/data/session-archiver"
LOG_FILE = LOG_DIR / "run.log"
UV = "/opt/homebrew/bin/uv"

# Extend PATH
os.environ["PATH"] = (
    f"/opt/homebrew/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:"
    + os.environ.get("PATH", "")
)


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[session-archive] {timestamp} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def run_step(args: list[str]) -> bool:
    """Run a uv python module step, appending output to log. Returns True on success."""
    cmd = [UV, "run", "python", "-m"] + args
    with open(LOG_FILE, "a") as f:
        result = subprocess.run(cmd, stdout=f, stderr=f, cwd=str(STATION_DIR))
    return result.returncode == 0


def run_redact_sweep() -> bool:
    """Run session redactor full_sweep via SDK (in-process). Returns True on success."""
    try:
        sys.path.insert(0, str(HOME / "workshop/libs/python/src"))
        from workshop.clients.session_redactor import SessionRedactorClient

        client = SessionRedactorClient()
        result = client.full_sweep(trigger="scheduled")
        log(
            f"  redact sweep: processed={result['files_processed']} "
            f"skipped={result['files_skipped']} "
            f"redactions={result['total_redactions']} "
            f"errors={result['errors']}"
        )
        return result["errors"] == 0
    except Exception as exc:
        log(f"  redact sweep error: {exc}")
        return False


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log("========== Daily session lifecycle started ==========")

    # Step 1: Redact sweep — catch sessions missed by SessionEnd hook
    log("Step 1/3: Redact sweep...")
    if run_redact_sweep():
        log("Step 1 OK")
    else:
        log("Step 1 FAILED — continuing anyway (archive still runs)")

    # Step 2: Scan sessions
    log("Step 2/3: Scanning sessions...")
    if run_step(["session_archiver", "scan", "--json"]):
        log("Step 2 OK")
    else:
        log("Step 2 FAILED — continuing anyway")

    # Step 3: Archive (execute mode with summaries + embeddings)
    log("Step 3/3: Archiving cold candidates...")
    if run_step(["session_archiver", "archive", "--execute", "--summarize", "--embed", "--json"]):
        log("Step 3 OK")
    else:
        log("Step 3 FAILED — continuing anyway")

    log("========== Daily session lifecycle complete ==========")


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

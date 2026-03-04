#!/usr/bin/env python3
"""
ws_session_archive.py — Daily 5:15AM session scan + archive

Pipeline (sequential):
  1. scan      — discover all sessions, update DB index
  2. archive   — compress cold candidates with summaries + embeddings

Logs: ~/.claude/data/session-archiver/run.log
"""

import os
import subprocess
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


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log("========== Daily session archive started ==========")

    # Step 1: Scan sessions
    log("Step 1/2: Scanning sessions...")
    if run_step(["session_archiver", "scan", "--json"]):
        log("Step 1 OK")
    else:
        log("Step 1 FAILED — continuing anyway")

    # Step 2: Archive (execute mode with summaries + embeddings)
    log("Step 2/2: Archiving cold candidates...")
    if run_step(["session_archiver", "archive", "--execute", "--summarize", "--embed", "--json"]):
        log("Step 2 OK")
    else:
        log("Step 2 FAILED — continuing anyway")

    log("========== Daily session archive complete ==========")


if __name__ == "__main__":
    main()

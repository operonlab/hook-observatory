#!/usr/bin/env python3
"""
ws_auto_survey.py — Wed/Fri 13:30 smart reminder for auto-survey

Triggered by launchd at 13:30 on class days.
Loops every 10 minutes, sending Bark reminders until URLs are provided.
Exits when:
  - Today's DailyRun status is 'running' or 'completed' (URLs provided)
  - Timeout reached (90 minutes = 15:00)
"""

import os
import subprocess
import time
from pathlib import Path

HOME = Path.home()
STATION_DIR = HOME / "workshop/stations/auto-survey"
UV = "/opt/homebrew/bin/uv"
POLL_INTERVAL = 600  # 10 minutes
MAX_DURATION = 5400  # 90 minutes

os.environ["PATH"] = (
    f"/opt/homebrew/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:"
    + os.environ.get("PATH", "")
)


def run_notify_check() -> str:
    """Run auto-survey notify-check. Returns stdout."""
    cmd = [
        UV,
        "run",
        "--project",
        str(STATION_DIR),
        "auto-survey",
        "notify-check",
    ]
    result = subprocess.run(cmd, cwd=str(STATION_DIR), capture_output=True, text=True)
    output = result.stdout.strip()
    print(output, flush=True)
    if result.stderr:
        print(result.stderr, end="", flush=True)
    return output


def try_line_reader() -> bool:
    """Phase 0: Try reading SurveyCake URLs from LINE Desktop.

    Returns True if pipeline was triggered successfully.
    """
    print("[ws_auto_survey] Phase 0: Trying LINE reader...", flush=True)
    cmd = [
        UV,
        "run",
        "--project",
        str(STATION_DIR),
        "auto-survey",
        "line-read",
        "--trigger",
    ]
    result = subprocess.run(cmd, cwd=str(STATION_DIR), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), flush=True)

    if result.returncode == 0:
        print("[ws_auto_survey] Phase 0 success — LINE reader triggered pipeline.", flush=True)
        return True

    print("[ws_auto_survey] Phase 0 failed — falling through to Bark reminder loop.", flush=True)
    return False


def main() -> None:
    # Phase 0: Try LINE reader first
    if try_line_reader():
        return

    # Phase 1: Bark reminder loop (fallback)
    print(f"[ws_auto_survey] Starting reminder loop (poll every {POLL_INTERVAL}s)", flush=True)
    start_time = time.time()

    while time.time() - start_time < MAX_DURATION:
        output = run_notify_check()

        # If already running or completed, URLs were provided — exit
        if "already" in output:
            print("[ws_auto_survey] URLs provided, exiting.", flush=True)
            return

        elapsed = int(time.time() - start_time)
        remaining = MAX_DURATION - elapsed
        print(
            f"[ws_auto_survey] Next check in {POLL_INTERVAL}s ({remaining}s remaining)",
            flush=True,
        )
        time.sleep(POLL_INTERVAL)

    print("[ws_auto_survey] Timeout reached (15:00), exiting.", flush=True)


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

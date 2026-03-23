#!/usr/bin/env python3
"""
ws_auto_survey.py — Wed/Fri 13:00 auto-survey LINE reader + fallback

Timeline:
  13:00       Cronicle triggers this script
  13:00~14:00 Phase 0: LINE poll every 10min (screenshot + OCR)
  14:00       Decision point:
              - URLs found → execute pipeline → Bark result
              - No URLs → Phase 1: Bark reminder loop until timeout
"""

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
STATION_DIR = HOME / "workshop/stations/auto-survey"
UV = "/opt/homebrew/bin/uv"

EXECUTION_HOUR = 14
LINE_POLL_INTERVAL = 600  # 10 minutes
BARK_POLL_INTERVAL = 600  # 10 minutes
MAX_DURATION = 7200  # 2 hours (13:00~15:00)

os.environ["PATH"] = (
    f"/opt/homebrew/bin:{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:"
    + os.environ.get("PATH", "")
)


def _run_auto_survey(*args: str) -> subprocess.CompletedProcess:
    cmd = [UV, "run", "--project", str(STATION_DIR), "auto-survey", *args]
    return subprocess.run(cmd, cwd=str(STATION_DIR), capture_output=True, text=True)


def try_line_read() -> bool:
    """Single LINE read attempt. Returns True if URLs found and saved to DB."""
    print("[ws_auto_survey] LINE read (screenshot + OCR)...", flush=True)
    result = _run_auto_survey("line-read")
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), flush=True)
    return result.returncode == 0


def get_today_status() -> dict[str, str]:
    """Get today's DailyRun status and URLs from DB via today-status command."""
    result = _run_auto_survey("today-status")
    if result.returncode != 0:
        return {}
    info = {}
    for line in result.stdout.strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            info[key.strip()] = value.strip()
    return info


def run_notify_check() -> str:
    """Send Bark reminder if needed. Returns stdout."""
    result = _run_auto_survey("notify-check")
    output = result.stdout.strip()
    print(output, flush=True)
    if result.stderr:
        print(result.stderr, end="", flush=True)
    return output


def trigger_pipeline(attend_url: str | None, quiz_url: str | None) -> None:
    """Execute the survey pipeline via auto-survey run."""
    args = ["run"]
    if attend_url:
        args += ["--attend-url", attend_url]
    if quiz_url:
        args += ["--quiz-url", quiz_url]
    print(f"[ws_auto_survey] Triggering pipeline: {' '.join(args)}", flush=True)
    result = _run_auto_survey(*args)
    if result.stdout:
        print(result.stdout.rstrip(), flush=True)
    if result.stderr:
        print(result.stderr.rstrip(), flush=True)


def main() -> None:
    start = time.time()

    # ── Phase 0: LINE poll (13:00 ~ 14:00) ──
    print("[ws_auto_survey] Phase 0: LINE poll started", flush=True)
    while datetime.now().hour < EXECUTION_HOUR:
        if time.time() - start > MAX_DURATION:
            break
        if try_line_read():
            print("[ws_auto_survey] Phase 0: URLs found, waiting for execution hour", flush=True)
            break
        print(f"[ws_auto_survey] No URLs yet, retry in {LINE_POLL_INTERVAL}s", flush=True)
        time.sleep(LINE_POLL_INTERVAL)

    # ── Wait until EXECUTION_HOUR ──
    now = datetime.now()
    if now.hour < EXECUTION_HOUR:
        target = now.replace(hour=EXECUTION_HOUR, minute=0, second=0, microsecond=0)
        wait_sec = int((target - now).total_seconds())
        if wait_sec > 0:
            print(f"[ws_auto_survey] Waiting {wait_sec}s until {EXECUTION_HOUR}:00", flush=True)
            time.sleep(wait_sec)

    # ── Decision point at EXECUTION_HOUR ──
    print(f"[ws_auto_survey] {EXECUTION_HOUR}:00 decision point", flush=True)
    status = get_today_status()

    if status.get("attend_url") or status.get("quiz_url"):
        # URLs available → execute pipeline
        trigger_pipeline(
            status.get("attend_url") or None,
            status.get("quiz_url") or None,
        )
        return

    # ── Phase 1: Bark reminder loop (14:00~) ──
    print(f"[ws_auto_survey] Phase 1: Bark reminders (every {BARK_POLL_INTERVAL}s)", flush=True)
    while time.time() - start < MAX_DURATION:
        run_notify_check()
        time.sleep(BARK_POLL_INTERVAL)

        # Check if URLs were provided manually (via web UI)
        status = get_today_status()
        if status.get("status") in ("running", "completed"):
            print("[ws_auto_survey] Pipeline handled externally, exiting.", flush=True)
            return
        if status.get("attend_url") or status.get("quiz_url"):
            print("[ws_auto_survey] URLs provided manually, triggering pipeline.", flush=True)
            trigger_pipeline(
                status.get("attend_url") or None,
                status.get("quiz_url") or None,
            )
            return

    print("[ws_auto_survey] Timeout reached, exiting.", flush=True)


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

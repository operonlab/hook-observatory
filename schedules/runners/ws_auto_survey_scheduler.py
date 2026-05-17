#!/usr/bin/env python3
"""ws_auto_survey_scheduler.py — Unified auto-survey state machine.

Replaces six separate jobs (start/run/stop × wed/fri) with one runner
that ticks every 30 minutes and decides what to do based on weekday
and hour. Behavior matches the original sextuplet exactly.

State table (Wed=3, Fri=5 via isoweekday)::

    10:00–10:29 → launchctl kickstart -k gui/$UID/com.workshop.auto-survey
    13:00–13:29 → /bin/bash ws_auto_survey.sh
    18:00–18:29 → launchctl kill TERM gui/$UID/com.workshop.auto-survey
    else        → no-op

Run with --dry-run to log the planned action without executing it.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / "workshop/outputs/scheduler/logs/ws-auto-survey-scheduler.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

SURVEY_SH = Path.home() / "workshop/schedules/runners/ws_auto_survey.sh"
DAEMON_LABEL = "com.workshop.auto-survey"


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001,S110 — log write is best-effort
        pass


def _service_target() -> str:
    return f"gui/{os.getuid()}/{DAEMON_LABEL}"


def kickstart_daemon(dry: bool) -> int:
    cmd = ["/bin/launchctl", "kickstart", "-k", _service_target()]
    _log(f"action=start cmd={' '.join(cmd)} dry_run={dry}")
    if dry:
        return 0
    return subprocess.run(cmd, check=False).returncode


def run_survey_script(dry: bool) -> int:
    cmd = ["/bin/bash", str(SURVEY_SH)]
    _log(f"action=run cmd={' '.join(cmd)} dry_run={dry}")
    if dry:
        return 0
    return subprocess.run(cmd, check=False).returncode


def stop_daemon(dry: bool) -> int:
    cmd = ["/bin/launchctl", "kill", "TERM", _service_target()]
    _log(f"action=stop cmd={' '.join(cmd)} dry_run={dry}")
    if dry:
        return 0
    return subprocess.run(cmd, check=False).returncode


def decide_action(now: datetime) -> str:
    """Return the action string for the given moment. ``"noop"`` when nothing to do.

    isoweekday: Mon=1 … Sun=7. Auto-survey only fires on Wed (3) and Fri (5).
    """
    if now.isoweekday() not in (3, 5):
        return "noop"
    return {10: "start", 13: "run", 18: "stop"}.get(now.hour, "noop")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="log the decision without executing"
    )
    args = parser.parse_args()

    now = datetime.now()
    action = decide_action(now)
    _log(
        f"tick weekday={now.isoweekday()} hour={now.hour:02d}:{now.minute:02d} "
        f"action={action}"
    )

    if action == "start":
        return kickstart_daemon(args.dry_run)
    if action == "run":
        return run_survey_script(args.dry_run)
    if action == "stop":
        return stop_daemon(args.dry_run)
    return 0  # noop


if __name__ == "__main__":
    sys.exit(main())

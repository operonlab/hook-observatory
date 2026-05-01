#!/usr/bin/env python3
"""cronicle_fail_alert.py — Detect job failures Cronicle silently swallows.

Cronicle wraps every job and reports `code: 0` regardless of inner script
exit. Real failures show up only in `last_exit_code: <non-zero>`. This
watcher tails the active Transaction.log, finds inner-script failures
since the last run, and pushes a Bark notification per failed event.

State file: ~/workshop/outputs/cronicle/last_offset.json
  Stores byte offset of Transaction.log already processed, so each run
  only scans new lines.

Usage:
  cronicle_fail_alert.py            # scan and alert
  cronicle_fail_alert.py --dry-run  # report without sending Bark
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

LOG_FILE = Path.home() / "workshop/vendor/cronicle/logs/Transaction.log"
STATE_DIR = Path.home() / "workshop/outputs/cronicle"
STATE_FILE = STATE_DIR / "last_offset.json"
NOTIFY_SH = Path.home() / "workshop/scripts/workshop-notify.sh"

# Skip these events — too high-frequency, alerts would spam.
# Also skip the watcher itself to avoid self-recursive alerting.
SKIP_EVENTS = {
    "ws-relay-auto-standby",
    "ws-relay-reaper",
    "ws-nginx-autoban",
    "ws-capture-watchdog",
    "Playwright Cache Cleanup",  # has its own quirks
    "ws-cronicle-fail-alert",  # self
}

EXIT_CODE_RE = re.compile(r"last_exit_code:\s*(\d+)")
TITLE_RE = re.compile(r"event_title:\s*([^|]+?)\s*\|")
JOB_ID_RE = re.compile(r"\bid:\s*(\w+)\s*\|")


def load_offset() -> int:
    if not STATE_FILE.exists():
        return 0
    try:
        return json.loads(STATE_FILE.read_text()).get("offset", 0)
    except (json.JSONDecodeError, OSError):
        return 0


def save_offset(offset: int) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"offset": offset}))


def send_bark(title: str, body: str) -> bool:
    if not NOTIFY_SH.exists():
        print(f"[warn] notify script missing: {NOTIFY_SH}", file=sys.stderr)
        return False
    try:
        result = subprocess.run(
            ["bash", str(NOTIFY_SH), title, body, "--bark", "--severity", "critical"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"[warn] bark send failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Detect only, don't send Bark")
    parser.add_argument("--reset", action="store_true", help="Reset offset to current end")
    args = parser.parse_args()

    if not LOG_FILE.exists():
        print(f"[error] log not found: {LOG_FILE}", file=sys.stderr)
        return 1

    current_size = LOG_FILE.stat().st_size

    if args.reset:
        save_offset(current_size)
        print(f"[reset] offset set to {current_size}")
        return 0

    last_offset = load_offset()

    # Log rotated (new file smaller than recorded offset) — restart from 0
    if last_offset > current_size:
        last_offset = 0

    if last_offset >= current_size:
        return 0  # nothing new

    failures: list[tuple[str, int, str]] = []
    with LOG_FILE.open("rb") as f:
        f.seek(last_offset)
        chunk = f.read()

    for raw in chunk.splitlines():
        line = raw.decode("utf-8", errors="replace")
        m = EXIT_CODE_RE.search(line)
        if not m:
            continue
        exit_code = int(m.group(1))
        if exit_code == 0:
            continue
        t = TITLE_RE.search(line)
        title = t.group(1).strip() if t else "<unknown>"
        if title in SKIP_EVENTS:
            continue
        j = JOB_ID_RE.search(line)
        job_id = j.group(1) if j else "?"
        failures.append((title, exit_code, job_id))

    save_offset(current_size)

    if not failures:
        return 0

    print(f"[fail-alert] {len(failures)} silent failure(s) detected:")
    for title, code, jid in failures:
        msg = f"exit {code} (job {jid})"
        print(f"  - {title}: {msg}")
        if not args.dry_run:
            send_bark(f"Cronicle: {title}", msg)

    return 0


if __name__ == "__main__":
    sys.exit(main())

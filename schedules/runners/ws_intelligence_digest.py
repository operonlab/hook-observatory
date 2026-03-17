#!/Users/joneshong/.local/bin/python3
"""Weekly intelligence digest → memvault flywheel bridge.

Runs every Monday at 9:00 AM:
1. Generates weekly digest for the previous week
2. The CLI auto-publishes to memvault (default behavior)
3. Triggers flywheel: digest → knowledge block → co-occurrence triples → KG

Cronicle event: ws-intelligence-digest
"""

import subprocess
import sys
from pathlib import Path

# ── Quota Gate ─────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.quota_gate import request_clearance

request_clearance("ws-intelligence-digest")


def main():
    print("[ws_intelligence_digest] Starting weekly digest...")

    # Run intelligence digest for last week (week_offset=1)
    # The CLI auto-publishes to memvault by default (use --no-publish to skip)
    result = subprocess.run(
        [
            "/Users/joneshong/.local/bin/python3",
            "/Users/joneshong/workshop/stations/session-intelligence/cli/intelligence.py",
            "digest",
            "--week-offset",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.stdout:
        print(result.stdout)

    if result.returncode != 0:
        print(f"[ERROR] digest failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    print("[ws_intelligence_digest] Done.")


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

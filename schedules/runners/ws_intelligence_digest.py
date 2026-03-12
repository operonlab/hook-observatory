#!/Users/joneshong/.local/bin/python3
"""Weekly intelligence digest → memvault flywheel bridge.

Runs every Monday at 9:00 AM:
1. Generates weekly digest for the previous week
2. Auto-publishes to memvault via intelligence/ingest endpoint
3. Triggers flywheel: digest → knowledge block → co-occurrence triples → KG

Cronicle event: ws-intelligence-digest
"""

import json
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
    result = subprocess.run(
        [
            "/Users/joneshong/.local/bin/python3",
            "/Users/joneshong/workshop/stations/session-intelligence/cli/intelligence.py",
            "digest",
            "--week-offset",
            "1",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        print(f"[ERROR] digest failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Parse digest data
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"[ERROR] Invalid JSON output: {result.stdout[:200]}", file=sys.stderr)
        sys.exit(1)

    period = data.get("period", {})
    iso_week = period.get("iso_week", "unknown")
    stats = data.get("summary_stats", {})

    print(f"[ws_intelligence_digest] Digest for {iso_week}:")
    print(f"  Sessions: {stats.get('total_sessions', 0)}")
    print(f"  Messages: {stats.get('total_messages', 0)}")
    print(f"  Projects: {stats.get('unique_projects', 0)}")

    # Publish to memvault via CLI (triggers flywheel event)
    content = json.dumps(data, ensure_ascii=False, default=str)
    publish_result = subprocess.run(
        [
            "/Users/joneshong/.local/bin/python3",
            "/Users/joneshong/workshop/core/cli/memvault.py",
            "intelligence-ingest",
            content,
            "--digest-type",
            "weekly",
            "--period",
            iso_week,
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if publish_result.returncode == 0:
        print(f"[ws_intelligence_digest] Published to memvault: {iso_week}")
    else:
        print(f"[WARN] Publish failed (non-fatal): {publish_result.stderr}", file=sys.stderr)

    print("[ws_intelligence_digest] Done.")


if __name__ == "__main__":
    main()

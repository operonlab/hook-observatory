#!/Users/joneshong/.local/bin/python3
"""
Anvil Telemetry Sync — catch-up for unsent local spool entries.

Reads ~/.claude/data/anvil-telemetry/pending.jsonl, POSTs unsent entries
to the Anvil API, and rewrites the file marking them as synced.

Usage:
    anvil-telemetry-sync              # sync all pending
    anvil-telemetry-sync --status     # show pending count
    anvil-telemetry-sync --dry-run    # count without sending

Designed to run:
  - On SessionStart hook (catch previous session's failures)
  - Manually when server was down for a while
  - Via cron/launchd for periodic catch-up
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ANVIL_API = os.environ.get("ANVIL_API", "http://127.0.0.1:4103")
SPOOL_DIR = Path.home() / ".claude" / "data" / "anvil-telemetry"
SPOOL_FILE = SPOOL_DIR / "pending.jsonl"
SYNCED_FILE = SPOOL_DIR / "synced.jsonl"


def read_spool() -> list[dict]:
    """Read all entries from the spool file."""
    if not SPOOL_FILE.exists():
        return []
    entries = []
    with open(SPOOL_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def post_to_anvil(entry: dict) -> bool:
    """POST a single invocation to Anvil API. Returns True on success."""
    payload = {
        "skill_name": entry["skill_name"],
        "session_id": entry.get("session_id", ""),
        "agent_model": entry.get("agent_model", ""),
        "success": entry.get("success", True),
        "error_message": entry.get("error_message"),
        "tool_calls_count": entry.get("tool_calls_count", 1),
        "payload": entry.get("payload", {}),
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{ANVIL_API}/api/anvil/invocations",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 201
    except (urllib.error.URLError, OSError):
        return False


def sync(dry_run: bool = False) -> tuple[int, int, int]:
    """Sync pending entries to Anvil. Returns (total, sent, failed)."""
    entries = read_spool()
    pending = [e for e in entries if not e.get("synced")]

    if not pending:
        return len(entries), 0, 0

    if dry_run:
        return len(entries), len(pending), 0

    sent = 0
    failed = 0
    synced_entries = []

    for entry in entries:
        if entry.get("synced"):
            synced_entries.append(entry)
            continue

        if post_to_anvil(entry):
            entry["synced"] = True
            sent += 1
        else:
            failed += 1
        synced_entries.append(entry)

    # Rewrite spool with updated sync status
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)

    # Move fully synced entries to archive, keep unsynced in pending
    still_pending = [e for e in synced_entries if not e.get("synced")]
    newly_synced = [e for e in synced_entries if e.get("synced")]

    # Append synced entries to archive
    if newly_synced:
        with open(SYNCED_FILE, "a") as f:
            for e in newly_synced:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # Rewrite pending with only unsynced entries
    with open(SPOOL_FILE, "w") as f:
        for e in still_pending:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    return len(entries), sent, failed


def status() -> None:
    """Print spool status."""
    entries = read_spool()
    pending = [e for e in entries if not e.get("synced")]
    synced_count = 0
    if SYNCED_FILE.exists():
        with open(SYNCED_FILE) as f:
            synced_count = sum(1 for line in f if line.strip())

    print(f"Spool: {SPOOL_FILE}")
    print(f"  Total in spool: {len(entries)}")
    print(f"  Pending sync:   {len(pending)}")
    print(f"  Archived:       {synced_count}")

    # Check Anvil API connectivity
    try:
        req = urllib.request.Request(f"{ANVIL_API}/api/anvil/invocations?limit=1")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            print(f"  Anvil DB total: {data.get('total', '?')}")
            print("  Anvil API:      reachable")
    except (urllib.error.URLError, OSError):
        print("  Anvil API:      UNREACHABLE")


def main():
    parser = argparse.ArgumentParser(description="Anvil Telemetry Sync")
    parser.add_argument("--status", action="store_true", help="Show spool status")
    parser.add_argument("--dry-run", action="store_true", help="Count without sending")
    args = parser.parse_args()

    if args.status:
        status()
        return

    total, sent, failed = sync(dry_run=args.dry_run)
    pending = total - sent

    if args.dry_run:
        print(f"Dry run: {sent} entries pending sync (total {total} in spool)")
    else:
        print(f"Synced: {sent} sent, {failed} failed, {pending - failed} already synced")
        if failed > 0:
            print(f"  {failed} entries remain pending (Anvil API may be down)")
            sys.exit(1)


if __name__ == "__main__":
    main()

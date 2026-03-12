#!/usr/bin/env python3
"""Quota Gate Client — request execution clearance from the Gate Authority.

Usage as library:
    from lib.quota_gate import request_clearance
    request_clearance("daily-briefing")  # exits if denied

Usage as CLI (for Cronicle command chaining):
    python3 schedules/lib/quota_gate.py daily-briefing
    # Exit 0 = allowed (or gate unreachable → fail-open)
    # Exit 78 = denied (EX_CONFIG — job not authorized at current quota level)

Cronicle integration:
    ~/.local/bin/python3 ~/workshop/schedules/lib/quota_gate.py daily-briefing && \
    ~/.local/bin/python3 ~/.claude/scripts/daily-briefing/run.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime

GATE_URL = "http://127.0.0.1:8795/api/quota/gate"
BARK_URL = "http://127.0.0.1:8090"


def _bark_notify(title: str, body: str) -> None:
    """Send Bark push notification (best-effort)."""
    try:
        encoded_title = urllib.parse.quote(title)
        encoded_body = urllib.parse.quote(body)
        url = f"{BARK_URL}/{encoded_title}/{encoded_body}?group=quota-gate&sound=silence"
        urllib.request.urlopen(url, timeout=3)
    except Exception:
        pass


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[quota-gate] {ts} {msg}", flush=True)


def request_clearance(job_name: str, *, notify: bool = True) -> dict | None:
    """Ask the Gate Authority for execution clearance.

    Returns the gate response dict if allowed, or calls sys.exit(0) if denied.
    On gate unreachable, returns None (fail-open — allows execution).
    """
    import urllib.parse

    try:
        encoded = urllib.parse.quote(job_name)
        resp = urllib.request.urlopen(f"{GATE_URL}?job={encoded}", timeout=5)
        data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        _log(f"Gate unreachable ({e}) — fail-open, proceeding")
        return None

    level = data.get("level", "?")
    max_level = data.get("max_level", "?")
    reason = data.get("reason", "")

    if data.get("allowed"):
        _log(f"Cleared: L{level} (max L{max_level}) — {reason}")
        return data

    _log(f"Denied: L{level} > max L{max_level} — {reason}")
    if notify:
        _bark_notify(
            f"排程降級: {job_name}",
            f"L{level} > max L{max_level}\n{reason}",
        )
    sys.exit(0)  # Exit 0 so Cronicle doesn't mark as failed


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <job-name>", file=sys.stderr)
        sys.exit(1)

    job_name = sys.argv[1]
    result = request_clearance(job_name)
    if result:
        # Print JSON for debugging / piping
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

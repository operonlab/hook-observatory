"""
Observability bridge — fire-and-forget event spool.

Appends every hook event as a single JSONL line to the spool file.
Latency: <1ms (no network, atomic single-line write).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from .base import ALLOW, HOME, HookResult

SPOOL_DIR = os.path.join(HOME, ".hook-observatory", "spool")
SPOOL_FILE = os.path.join(SPOOL_DIR, "events.jsonl")


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if not raw_input.strip():
        return ALLOW

    os.makedirs(SPOOL_DIR, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    line = json.dumps({"event_type": event_type, "ts": ts, "data": json.loads(raw_input)},
                       ensure_ascii=False, separators=(",", ":"))

    try:
        with open(SPOOL_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass

    return ALLOW

"""
Session cost tracker — fire-and-forget response counter.

Appends one JSONL line per Stop event to track response counts per session.
All aggregation is deferred to the /session-cost command.

Latency: <1ms (atomic single-line append, no computation).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from .base import ALLOW, HOME, HookResult

DATA_DIR = os.path.join(HOME, ".claude", "data", "session-cost")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.jsonl")

# Per-process counter: session_id → response_index
_counters: dict[str, int] = {}


def _parse_session_id(raw_input: str) -> str:
    """Extract session_id from raw hook payload. Returns empty string on failure."""
    try:
        parsed = json.loads(raw_input)
        # Claude Code Stop event embeds session_id at top level
        sid = parsed.get("session_id", "")
        if not sid:
            # Some payloads nest it under tool_input
            sid = parsed.get("tool_input", {}).get("session_id", "")
        return str(sid) if sid else ""
    except (json.JSONDecodeError, AttributeError):
        return ""


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """Track response count for each session. Always returns ALLOW."""
    if not raw_input.strip():
        return ALLOW

    try:
        session_id = _parse_session_id(raw_input) or "unknown"

        # Increment per-session counter (resets on process restart)
        _counters[session_id] = _counters.get(session_id, 0) + 1
        response_index = _counters[session_id]

        ts = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = json.dumps(
            {
                "session_id": session_id,
                "ts": ts,
                "tool_name": tool_name,
                "response_index": response_index,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SESSIONS_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:  # noqa: S110
        pass  # fire-and-forget: never block the hook pipeline

    return ALLOW

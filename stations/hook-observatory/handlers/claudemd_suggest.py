"""
CLAUDE.md suggestion notifier — SessionStart handler.

Reads pending suggestions from the staging file written by extract.py
and injects a notification message at session start so the user can review.
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import ALLOW, HookResult, message

STAGING_FILE = Path.home() / ".claude" / "data" / "claudemd-suggestions" / "pending.jsonl"
MAX_PREVIEW = 3


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if event_type != "SessionStart":
        return ALLOW

    pending = _load_pending()
    if not pending:
        return ALLOW

    parts = [f"## CLAUDE.md 建議待審 ({len(pending)} 條)"]
    for entry in pending[:MAX_PREVIEW]:
        topic = entry.get("source_topic", "")
        suggestion = entry.get("suggestion", "")
        prefix = f"[{topic}] " if topic else ""
        parts.append(f"- {prefix}{suggestion}")

    if len(pending) > MAX_PREVIEW:
        parts.append(f"  ... 還有 {len(pending) - MAX_PREVIEW} 條")

    parts.append("使用 `/review-claudemd` 審閱並套用")

    return message("\n".join(parts))


def _load_pending() -> list[dict]:
    """Load unreviewed entries from staging JSONL."""
    if not STAGING_FILE.is_file():
        return []
    try:
        entries = []
        for line in STAGING_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if not entry.get("reviewed", False):
                    entries.append(entry)
            except json.JSONDecodeError:
                continue
        return entries
    except Exception:
        return []

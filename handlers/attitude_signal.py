"""
Attitude signal collector -- implicit attitude signals from hook events.

Collects two signal types:
1. Notification (tool_denied) -> autonomy_level correction
2. SessionEnd -> session statistics (deny count, message count, tool density)

Output: ~/Claude/memvault/corrections/auto/{YYYY-MM}/{date}.jsonl
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .base import ALLOW, HOME, HookResult

CORRECTIONS_DIR = Path(HOME) / "Claude" / "memvault" / "corrections" / "auto"
SPOOL_DIR = Path(HOME) / ".hook-observatory" / "spool"
SPOOL_FILE = SPOOL_DIR / "events.jsonl"


def _write_correction(category: str, fact: str, session_id: str = "") -> None:
    """Append a correction record to the auto corrections JSONL."""
    now = datetime.now()
    month_dir = CORRECTIONS_DIR / now.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)

    out_file = month_dir / f"{now.strftime('%Y-%m-%d')}.jsonl"
    record = {
        "fact": fact,
        "category": category,
        "session_id": session_id,
        "timestamp": now.isoformat(timespec="seconds"),
        "source": "attitude_signal",
    }
    with open(out_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _handle_notification(tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """Handle Notification events -- detect tool denials."""
    try:
        data = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
    except (json.JSONDecodeError, TypeError):
        return ALLOW

    # Check for denial notification
    message = data.get("message", "") or ""
    notification_data = data.get("data", data)

    # Claude Code sends denial info in various formats
    denied_tool = ""
    if "denied" in message.lower():
        denied_tool = notification_data.get("tool_name", "") or tool_name
    elif notification_data.get("type") == "tool_denied":
        denied_tool = notification_data.get("tool_name", "")

    if denied_tool:
        session_id = notification_data.get("session_id", "")
        _write_correction(
            category="autonomy_level",
            fact=f"使用者 deny {denied_tool}，偏好更多確認再執行",
            session_id=session_id,
        )

    return ALLOW


def _handle_session_end(tool_input: dict, raw_input: str) -> HookResult:
    """Handle SessionEnd -- analyze spool statistics for the session."""
    try:
        data = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
    except (json.JSONDecodeError, TypeError):
        return ALLOW

    session_id = data.get("data", {}).get("session_id", "") or data.get("session_id", "")
    if not session_id:
        return ALLOW

    # Read spool and filter for this session's events
    if not SPOOL_FILE.is_file():
        return ALLOW

    try:
        session_events = []
        with open(SPOOL_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                    evt_sid = evt.get("data", {}).get("session_id", "")
                    if evt_sid == session_id:
                        session_events.append(evt)
                except json.JSONDecodeError:
                    continue
    except Exception:
        return ALLOW

    if not session_events:
        return ALLOW

    # Count statistics
    deny_count = 0
    message_count = 0
    tool_count = 0

    for evt in session_events:
        event_type = evt.get("event_type", "")
        evt_data = evt.get("data", {})

        if event_type == "Notification":
            msg = evt_data.get("message", "") or ""
            if "denied" in msg.lower() or evt_data.get("type") == "tool_denied":
                deny_count += 1

        if event_type == "UserPromptSubmit":
            message_count += 1

        if event_type in ("PreToolUse", "PostToolUse"):
            tool_count += 1

    # Infer attitude signals
    if deny_count >= 3:
        _write_correction(
            category="autonomy_level",
            fact=f"本 session deny {deny_count} 次，使用者偏好更多確認",
            session_id=session_id,
        )

    if message_count > 0 and tool_count / message_count > 15:
        _write_correction(
            category="verbosity",
            fact=f"高工具密度 ({tool_count}/{message_count})，使用者可能偏好精簡對話",
            session_id=session_id,
        )

    return ALLOW


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """Main entry point -- dispatches by event_type."""
    if event_type == "Notification":
        return _handle_notification(tool_name, tool_input, raw_input)
    if event_type == "SessionEnd":
        return _handle_session_end(tool_input, raw_input)
    return ALLOW

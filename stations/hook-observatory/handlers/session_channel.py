"""
Session Channel auto-announce handler.

Events:
  SessionStart → announce session join to 'sessions' topic
  Stop         → announce session activity to 'sessions' topic (debounced)

Fire-and-forget HTTP POST to session-channel station (localhost:10101).
Fails silently if station is not running.
"""

from __future__ import annotations

import json
import os
import time

from .base import ALLOW, HookResult, run_background
from .hook_config import get_service

_BASE_URL = get_service("session_channel_url")
_LOCAL_KEY = "change-me-in-production"
_DEBOUNCE_FILE = "/tmp/session-channel-stop-debounce-{pane}.ts"  # noqa: S108
_DEBOUNCE_SECONDS = 60  # Don't announce Stop more than once per minute per pane


def _pane_id() -> str:
    pane = os.environ.get("TMUX_PANE", "")
    return pane.replace("%", "pane-") if pane else f"pid-{os.getpid()}"


def _send_async(topic: str, text: str, priority: str = "normal", tag: str = "") -> None:
    """Fire-and-forget POST to session-channel. Non-blocking."""
    body = {
        "topic": topic,
        "text": text,
        "sender": _pane_id(),
        "priority": priority,
    }
    if tag:
        body["tag"] = tag

    # Use curl for fire-and-forget (no Python dependency on httpx in hook env)
    cmd = (
        f"curl -s -o /dev/null -m 2 -X POST {_BASE_URL}/api/messages "
        f"-H 'Content-Type: application/json' "
        f"-H 'x-local-key: {_LOCAL_KEY}' "
        f"-d '{json.dumps(body)}'"
    )
    run_background(cmd)


def _read_task_state() -> str:
    """Read the current task description from the voice state file."""
    pane = os.environ.get("TMUX_PANE", "")
    if not pane:
        return ""
    state_file = f"/tmp/claude-task-{pane.replace('%', '')}.txt"  # noqa: S108
    try:
        return open(state_file).read().strip()
    except (FileNotFoundError, PermissionError):
        return ""


def _stop_debounced() -> bool:
    """Check if Stop was already announced recently for this pane."""
    pane = _pane_id()
    path = _DEBOUNCE_FILE.format(pane=pane)
    now = time.time()
    try:
        ts = float(open(path).read().strip())
        if now - ts < _DEBOUNCE_SECONDS:
            return True
    except (FileNotFoundError, ValueError):
        pass
    try:
        with open(path, "w") as f:
            f.write(str(now))
    except OSError:
        pass
    return False


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """Handle SessionStart and Stop events."""

    if event_type == "SessionStart":
        # Parse session info from raw_input
        cwd = ""
        try:
            parsed = json.loads(raw_input)
            cwd = parsed.get("tool_input", {}).get("cwd", "")
        except (json.JSONDecodeError, AttributeError):
            pass

        short_cwd = cwd.replace(os.path.expanduser("~"), "~") if cwd else "?"
        _send_async("sessions", f"joined — {short_cwd}", tag="start")
        return ALLOW

    if event_type == "Stop":
        if _stop_debounced():
            return ALLOW

        task = _read_task_state()
        if task:
            # Detect relay pane — pending file exists when relay is waiting
            relay_meta = ""
            pane = os.environ.get("TMUX_PANE", "")
            if pane:
                pane_safe = pane.replace("%", "")
                if os.path.isfile(f"/tmp/relay-pending-{pane_safe}.channel"):  # noqa: S108
                    relay_meta = f" [relay:%{pane_safe}]"
            _send_async("sessions", f"done: {task}{relay_meta}", tag="stop")
        return ALLOW

    return ALLOW

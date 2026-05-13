"""
Plan-to-Implementation gate — detect ExitPlanMode and inject context reminder.

Handles two events:
  - PostToolUse (ExitPlanMode): Write marker file with plan path + timestamp
  - UserPromptSubmit: If marker exists, inject reminder to save plan to memory
    and consider starting a new session. One-shot: marker deleted after use.

Marker auto-expires after 1 hour to prevent stale triggers.
"""

from __future__ import annotations

import json
import os
import time

from .base import ALLOW, HookResult, text_result

_MARKER_DIR = os.path.join(os.path.expanduser("~"), ".hook-observatory", "markers")
_MARKER_PREFIX = ".plan-approved-"
_MARKER_TTL_SECONDS = 3600  # 1 hour


def _marker_path() -> str:
    session_id = os.environ.get("CLAUDE_SESSION_ID", "unknown")
    return os.path.join(_MARKER_DIR, f"{_MARKER_PREFIX}{session_id}")


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if event_type == "PostToolUse" and tool_name == "ExitPlanMode":
        return _on_exit_plan_mode(tool_input)

    if event_type == "UserPromptSubmit":
        return _on_user_prompt()

    return ALLOW


def _on_exit_plan_mode(tool_input: dict) -> HookResult:
    """Write marker file when exiting plan mode."""
    marker = _marker_path()
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        data = {
            "timestamp": time.time(),
            "plan_path": tool_input.get("plan_path", ""),
        }
        with open(marker, "w") as f:
            json.dump(data, f)
    except OSError:
        pass  # fail-open: don't block on write failure
    return ALLOW


def _on_user_prompt() -> HookResult:
    """Check for plan-approved marker and inject reminder if found."""
    marker = _marker_path()

    try:
        if not os.path.exists(marker):
            return ALLOW

        with open(marker) as f:
            data = json.load(f)

        # Check TTL — ignore stale markers
        ts = data.get("timestamp", 0)
        if time.time() - ts > _MARKER_TTL_SECONDS:
            os.unlink(marker)
            return ALLOW

        # One-shot: delete marker before injecting
        os.unlink(marker)

        plan_path = data.get("plan_path", "")
        path_hint = f"\n- Plan file: `{plan_path}`" if plan_path else ""

        return text_result(
            f"## Plan-to-Impl Gate\n"
            f"剛完成計畫階段 (plan mode 消耗了大量 context)。建議:\n"
            f"1. 將計畫中的關鍵決策存到 memory (避免 compact 後遺失)\n"
            f"2. 考慮開新 session 以乾淨 context 開始實作{path_hint}"
        )
    except (OSError, json.JSONDecodeError, KeyError):
        # fail-open
        return ALLOW

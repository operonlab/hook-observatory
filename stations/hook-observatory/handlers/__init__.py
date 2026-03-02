"""
Unified hook handler registry and dispatcher.

All hook events route through dispatch() which:
1. Matches handlers by event_type + tool_name
2. Runs matching handlers sequentially
3. Merges decisions (block > approve > passthrough)
4. Returns final output (JSON or passthrough text)
"""

from __future__ import annotations

import json
from collections.abc import Callable

# Import all handler modules
from . import (
    auto_format,
    bash_safety,
    cleanup_versions,
    external,
    observability,
    relay_signal,
    sentinel_notify,
    skill_security,
    verify_commit,
    voice_notify,
)
from .base import ALLOW, HookResult

# Type alias for handler functions
Handler = Callable[[str, str, dict, str], HookResult]


# ---------------------------------------------------------------------------
# Registry: event_type -> [(matcher_or_None, handler_fn), ...]
#   matcher=None  → always run (catch-all)
#   matcher="A|B" → run only when tool_name ∈ {A, B}
# ---------------------------------------------------------------------------

REGISTRY: dict[str, list[tuple[str | None, Handler]]] = {
    "PreToolUse": [
        ("AskUserQuestion",  voice_notify.handle),
        ("Bash",             verify_commit.handle),
        ("Bash",             bash_safety.handle),
        ("Bash",             sentinel_notify.handle),
        ("Write|Edit",       skill_security.handle),
        (None,               observability.handle),
    ],
    "PostToolUse": [
        ("Edit|Write",       auto_format.handle),
        ("Skill",            external.skill_tracker),
        (None,               observability.handle),
    ],
    "Stop": [
        (None,               relay_signal.handle),
        (None,               voice_notify.handle),
        (None,               observability.handle),
    ],
    "SessionEnd": [
        (None,               external.redact_session),
        (None,               external.extract),
        (None,               observability.handle),
    ],
    "UserPromptSubmit": [
        (None,               external.recall),
        (None,               observability.handle),
    ],
    "SessionStart": [
        (None,               external.sync_login),
        (None,               cleanup_versions.handle),
        (None,               observability.handle),
    ],
    "SubagentStart": [
        (None,               observability.handle),
    ],
    "SubagentStop": [
        (None,               observability.handle),
    ],
    "PreCompact": [
        (None,               observability.handle),
    ],
}


def _matches(matcher: str | None, tool_name: str) -> bool:
    """Check if tool_name matches the pipe-delimited matcher pattern."""
    if matcher is None:
        return True
    return tool_name in matcher.split("|")


def dispatch(event_type: str, raw_input: str) -> str:
    """
    Main entry point. Routes to matching handlers, merges results.

    Returns:
        str: JSON string (for most events) or passthrough text (UserPromptSubmit)
    """
    # Parse input once
    tool_name = ""
    tool_input: dict = {}
    try:
        if raw_input.strip():
            parsed = json.loads(raw_input)
            tool_name = parsed.get("tool_name", "")
            tool_input = parsed.get("tool_input", {})
    except (json.JSONDecodeError, AttributeError):
        pass

    handlers = REGISTRY.get(event_type, [])

    # Accumulators
    decision: str | None = None
    reason = ""
    messages: list[str] = []
    passthrough_parts: list[str] = []

    for matcher, handler_fn in handlers:
        if not _matches(matcher, tool_name):
            continue

        try:
            result = handler_fn(event_type, tool_name, tool_input, raw_input)
        except Exception:
            result = ALLOW

        # Merge decisions — block always wins
        if result.decision == "block":
            decision = "block"
            reason = result.reason
        elif result.decision == "approve" and decision != "block":
            decision = "approve"

        if result.message:
            messages.append(result.message)

        if result.text:
            passthrough_parts.append(result.text)

    # --- Build output ---
    if event_type == "UserPromptSubmit" and passthrough_parts:
        return "\n".join(passthrough_parts)

    output: dict = {}
    if decision:
        output["decision"] = decision
    if decision == "block" and reason:
        output["reason"] = reason
    if messages:
        output["message"] = "; ".join(messages)
    return json.dumps(output)

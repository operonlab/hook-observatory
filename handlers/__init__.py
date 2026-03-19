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
    anvil_telemetry,
    attitude_signal,
    auto_format,
    bash_safety,
    claudemd_suggest,
    cleanup_versions,
    context_inject,
    external,
    memory_sync,
    observability,
    pm_autopilot,
    relay_signal,
    rtk_rewrite,
    sentinel_notify,
    session_channel,
    session_namer,
    session_pipeline,
    skill_security,
    verify_commit,
    verify_completion,
    voice_notify,
)
from . import (
    context_supervisor as context_supervisor,
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
        ("AskUserQuestion", voice_notify.handle),
        ("Bash", verify_commit.handle),
        ("Bash", bash_safety.handle),
        ("Bash", sentinel_notify.handle),
        ("Bash", rtk_rewrite.handle),  # after safety — rewrite for token savings
        ("Write|Edit", skill_security.handle),
        # context_supervisor: disabled — concept good, scoring inaccurate
        (None, observability.handle),
    ],
    "PostToolUse": [
        ("Edit|Write", auto_format.handle),
        ("Edit|Write", memory_sync.handle),
        ("Bash", sentinel_notify.handle),
        ("Bash", pm_autopilot.handle),
        (None, anvil_telemetry.handle),
        ("Skill", external.skill_tracker),
        # context_supervisor: disabled
        (None, observability.handle),
    ],
    "Stop": [
        (None, session_namer.handle),
        (None, relay_signal.handle),
        (None, session_channel.handle),
        (None, pm_autopilot.handle),
        (None, voice_notify.handle),
        # context_supervisor: disabled
        (None, observability.handle),
    ],
    "Notification": [
        (None, attitude_signal.handle),
        (None, observability.handle),
    ],
    "SessionEnd": [
        (None, session_pipeline.handle),
        (None, attitude_signal.handle),
        (None, observability.handle),
    ],
    "UserPromptSubmit": [
        # context_supervisor: disabled
        (None, external.recall),
        (None, session_namer.handle_color_hint),
        (None, anvil_telemetry.handle),
        (None, observability.handle),
    ],
    "SessionStart": [
        (None, external.sync_login),
        (None, anvil_telemetry.handle),
        (None, session_channel.handle),
        (None, claudemd_suggest.handle),
        (None, cleanup_versions.handle),
        (None, pm_autopilot.handle),
        # context_supervisor: disabled
        (None, observability.handle),
    ],
    "SubagentStart": [
        (None, context_inject.handle),
        (None, observability.handle),
    ],
    "SubagentStop": [
        (None, verify_completion.handle),
        (None, voice_notify.handle),
        (None, observability.handle),
    ],
    "PreCompact": [
        # context_supervisor: disabled
        (None, external.progressive_extract),
        (None, observability.handle),
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
    updated_input: dict | None = None

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

        if result.updated_input is not None:
            updated_input = result.updated_input

    # --- Build output ---
    if event_type == "UserPromptSubmit" and passthrough_parts:
        return "\n".join(passthrough_parts)

    # Block wins — no rewrite
    if decision == "block":
        output: dict = {"decision": decision}
        if reason:
            output["reason"] = reason
        if messages:
            output["message"] = "; ".join(messages)
        return json.dumps(output)

    # Rewrite — use hookSpecificOutput format
    if updated_input is not None:
        hook_output: dict = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "RTK auto-rewrite",
                "updatedInput": updated_input,
            }
        }
        return json.dumps(hook_output)

    # Normal case
    output = {}
    if decision:
        output["decision"] = decision
    if messages:
        output["message"] = "; ".join(messages)
    return json.dumps(output)

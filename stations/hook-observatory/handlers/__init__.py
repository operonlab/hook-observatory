"""
Unified hook handler registry and dispatcher.

All hook events route through dispatch() which:
1. Matches handlers by event_type + tool_name
2. Runs critical handlers first (always, no budget)
3. Runs deferrable handlers with a 5s time budget
4. Merges decisions (block > approve > passthrough)
5. Returns final output (JSON or passthrough text)
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

# Import all handler modules
from . import (
    agent_naming,
    anvil_telemetry,
    attitude_signal,
    auto_format,
    bash_safety,
    claudemd_suggest,
    cleanup_versions,
    context_inject,
    context_relay,
    external,
    instinct_distiller,
    memory_sync,
    observability,
    plan_impl_gate,
    pm_autopilot,
    relay_signal,
    review_gate,
    rtk_rewrite,
    schedule_sync,
    secret_scan,
    sentinel_notify,
    session_channel,
    session_cost,
    session_namer,
    session_pipeline,
    skill_security,
    utility_watchdog,
    verify_commit,
    verify_completion,
    voice_notify,
)
from . import (
    context_supervisor as context_supervisor,
)
from .base import ALLOW, HookResult
from .hook_config import cfg as cfg
from .hook_config import get_budget_ms, is_handler_enabled

# Type alias for handler functions
Handler = Callable[[str, str, dict, str], HookResult]

# ---------------------------------------------------------------------------
# Blocking budget — deferrable handlers get a 5-second window per dispatch.
# Critical handlers always run regardless of elapsed time.
# ---------------------------------------------------------------------------

# Maximum milliseconds for deferrable handlers per event dispatch
BLOCKING_BUDGET_MS = get_budget_ms()

# These handlers always run, regardless of time budget (safety / security)
CRITICAL_HANDLERS: set[Handler] = {
    agent_naming.handle,
    bash_safety.handle,
    secret_scan.handle,
    skill_security.handle,
    verify_commit.handle,
    review_gate.handle,
}


# ---------------------------------------------------------------------------
# Registry: event_type -> [(matcher_or_None, handler_fn), ...]
#   matcher=None  → always run (catch-all)
#   matcher="A|B" → run only when tool_name ∈ {A, B}
# ---------------------------------------------------------------------------

REGISTRY: dict[str, list[tuple[str | None, Handler]]] = {
    "PreToolUse": [
        ("Agent", agent_naming.handle),
        ("AskUserQuestion", voice_notify.handle),
        ("Bash", verify_commit.handle),
        ("Bash", bash_safety.handle),
        ("Bash", secret_scan.handle),
        ("Bash", sentinel_notify.handle),
        ("Bash", rtk_rewrite.handle),  # after safety — rewrite for token savings
        ("Write|Edit", skill_security.handle),
        # context_supervisor: disabled — concept good, scoring inaccurate
        (None, observability.handle),
    ],
    "PostToolUse": [
        ("Edit|Write", auto_format.handle),
        ("Edit|Write", memory_sync.handle),
        ("Edit|Write", schedule_sync.handle),
        ("Bash", sentinel_notify.handle),
        ("Bash", pm_autopilot.handle),
        (None, anvil_telemetry.handle),
        ("Skill", external.skill_tracker),
        ("ExitPlanMode", plan_impl_gate.handle),
        # context_supervisor: disabled
        (None, observability.handle),
    ],
    "Stop": [
        (None, review_gate.handle),  # review gate — check uncommitted code changes
        (None, session_namer.handle),
        (None, relay_signal.handle),
        (None, session_channel.handle),
        (None, pm_autopilot.handle),
        (None, voice_notify.handle),
        (None, session_cost.handle),  # response counter — before observability
        # context_supervisor: disabled
        (None, observability.handle),
    ],
    "Notification": [
        (None, attitude_signal.handle),
        (None, observability.handle),
    ],
    "SessionEnd": [
        (None, session_pipeline.handle),
        (None, instinct_distiller.handle),
        (None, utility_watchdog.handle),
        (None, attitude_signal.handle),
        (None, observability.handle),
    ],
    "UserPromptSubmit": [
        # context_supervisor: disabled
        (None, external.recall),
        (None, plan_impl_gate.handle),
        (None, session_namer.handle_color_hint),
        (None, anvil_telemetry.handle),
        (None, observability.handle),
    ],
    "SessionStart": [
        (None, external.sync_login),
        (None, anvil_telemetry.handle),
        (None, session_channel.handle),
        (None, context_relay.handle),
        (None, claudemd_suggest.handle),
        (None, instinct_distiller.handle),
        (None, cleanup_versions.handle),
        (None, pm_autopilot.handle),
        (None, utility_watchdog.handle),
        # context_supervisor: disabled
        (None, observability.handle),
    ],
    "SubagentStart": [
        (None, context_inject.handle),
        (None, voice_notify.handle),
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
        (None, context_relay.handle),
        (None, observability.handle),
    ],
}


# ---------------------------------------------------------------------------
# Filter disabled handlers based on config.yaml / config.local.yaml
# ---------------------------------------------------------------------------

# Map handler function → handler module name (for config lookup)
_HANDLER_MODULE_MAP: dict[Handler, str] = {}
for _mod_name, _mod in [
    ("agent_naming", agent_naming),
    ("anvil_telemetry", anvil_telemetry),
    ("attitude_signal", attitude_signal),
    ("auto_format", auto_format),
    ("bash_safety", bash_safety),
    ("claudemd_suggest", claudemd_suggest),
    ("cleanup_versions", cleanup_versions),
    ("context_inject", context_inject),
    ("context_relay", context_relay),
    ("instinct_distiller", instinct_distiller),
    ("memory_sync", memory_sync),
    ("observability", observability),
    ("plan_impl_gate", plan_impl_gate),
    ("pm_autopilot", pm_autopilot),
    ("relay_signal", relay_signal),
    ("review_gate", review_gate),
    ("rtk_rewrite", rtk_rewrite),
    ("schedule_sync", schedule_sync),
    ("secret_scan", secret_scan),
    ("sentinel_notify", sentinel_notify),
    ("session_channel", session_channel),
    ("session_cost", session_cost),
    ("session_namer", session_namer),
    ("session_pipeline", session_pipeline),
    ("skill_security", skill_security),
    ("utility_watchdog", utility_watchdog),
    ("verify_commit", verify_commit),
    ("verify_completion", verify_completion),
    ("voice_notify", voice_notify),
]:
    _HANDLER_MODULE_MAP[_mod.handle] = _mod_name

# Also map external.* functions
for _attr in ("recall", "skill_tracker", "progressive_extract", "sync_login"):
    _fn = getattr(external, _attr, None)
    if _fn:
        _HANDLER_MODULE_MAP[_fn] = "external"


def _filter_registry() -> None:
    """Remove disabled handlers from REGISTRY and CRITICAL_HANDLERS."""
    for event_type in list(REGISTRY.keys()):
        REGISTRY[event_type] = [
            (m, h)
            for m, h in REGISTRY[event_type]
            if is_handler_enabled(_HANDLER_MODULE_MAP.get(h, ""))
        ]

    disabled_critical = {
        h for h in CRITICAL_HANDLERS if not is_handler_enabled(_HANDLER_MODULE_MAP.get(h, ""))
    }
    CRITICAL_HANDLERS.difference_update(disabled_critical)


_filter_registry()


def _matches(matcher: str | None, tool_name: str) -> bool:
    """Check if tool_name matches the pipe-delimited matcher pattern."""
    if matcher is None:
        return True
    return tool_name in matcher.split("|")


def _merge_result(result: HookResult, state: dict) -> None:
    """
    Merge a handler result into the mutable accumulator state dict.

    state keys: decision, reason, messages, passthrough_parts, updated_input
    """
    if result.decision == "block":
        state["decision"] = "block"
        state["reason"] = result.reason
    elif result.decision == "approve" and state["decision"] != "block":
        state["decision"] = "approve"

    if result.message:
        state["messages"].append(result.message)

    if result.text:
        state["passthrough_parts"].append(result.text)

    if result.updated_input is not None:
        state["updated_input"] = result.updated_input


def dispatch(event_type: str, raw_input: str) -> str:
    """
    Main entry point. Routes to matching handlers, merges results.

    Handlers are split into two phases:
    - Phase 1 (critical): always run, no time budget (safety / security)
    - Phase 2 (deferrable): run within BLOCKING_BUDGET_MS; extras are skipped

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

    # Split by criticality
    critical = [(m, h) for m, h in handlers if h in CRITICAL_HANDLERS]
    deferrable = [(m, h) for m, h in handlers if h not in CRITICAL_HANDLERS]

    # Shared accumulator state
    state: dict = {
        "decision": None,
        "reason": "",
        "messages": [],
        "passthrough_parts": [],
        "updated_input": None,
    }

    start = time.monotonic()

    # --- Phase 1: Critical handlers — always run, no budget ---
    for matcher, handler_fn in critical:
        if not _matches(matcher, tool_name):
            continue
        try:
            result = handler_fn(event_type, tool_name, tool_input, raw_input)
        except Exception:
            result = ALLOW
        _merge_result(result, state)

    # --- Phase 2: Deferrable handlers — subject to time budget ---
    skipped_count = 0
    for matcher, handler_fn in deferrable:
        if not _matches(matcher, tool_name):
            continue

        elapsed_ms = (time.monotonic() - start) * 1000
        if elapsed_ms > BLOCKING_BUDGET_MS:
            skipped_count += 1
            continue

        try:
            result = handler_fn(event_type, tool_name, tool_input, raw_input)
        except Exception:
            result = ALLOW
        _merge_result(result, state)

    if skipped_count > 0:
        # Log but don't block — skipped handlers were non-critical
        state["messages"].append(f"⏱️ {skipped_count} handler(s) skipped (budget exceeded)")

    # Unpack state
    decision = state["decision"]
    reason = state["reason"]
    messages: list[str] = state["messages"]
    passthrough_parts: list[str] = state["passthrough_parts"]
    updated_input: dict | None = state["updated_input"]

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

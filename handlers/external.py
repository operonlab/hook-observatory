"""
External handler wrappers — subprocess calls to scripts that live outside hook-observatory.

These scripts are part of other systems (memvault, session-redactor, playwright).
They're wrapped here to maintain the unified handler interface while keeping
the source of truth in their respective repos.
"""

from __future__ import annotations

import os

from .base import HOME, HookResult, call_external_script

MEMVAULT_SCRIPTS = os.path.join(HOME, "workshop", "mcp", "memvault", "scripts")


def recall(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """UserPromptSubmit: memvault recall — returns markdown context."""
    return call_external_script(
        os.path.join(MEMVAULT_SCRIPTS, "recall-v2.sh"),
        input_data=raw_input,
        timeout=15,
    )


def extract(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """SessionEnd: async memory extraction pipeline."""
    return call_external_script(
        os.path.join(MEMVAULT_SCRIPTS, "extract-v2-async.sh"),
        input_data=raw_input,
        timeout=5,
    )


def skill_tracker(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """PostToolUse/Skill: track skill usage to Core API."""
    return call_external_script(
        os.path.join(MEMVAULT_SCRIPTS, "skill-tracker-v2.sh"),
        input_data=raw_input,
        timeout=5,
    )


def redact_session(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """SessionEnd: redact sensitive data from transcript."""
    return call_external_script(
        os.path.join(HOME, "Claude", "projects", "session-redactor", "scripts", "redact-session.sh"),
        input_data=raw_input,
        timeout=10,
    )


def sync_login(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """SessionStart: sync Playwright profile from master."""
    return call_external_script(
        os.path.join(HOME, ".playwright-profiles", "sync-login.sh") + " --hook",
        input_data=raw_input,
        timeout=15,
    )

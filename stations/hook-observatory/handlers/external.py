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
        os.path.join(MEMVAULT_SCRIPTS, "recall_v2.py"),
        input_data=raw_input,
        timeout=15,
    )


def extract(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """SessionEnd: async memory extraction pipeline."""
    return call_external_script(
        os.path.join(MEMVAULT_SCRIPTS, "extract_async.py"),
        input_data=raw_input,
        timeout=5,
    )


def skill_tracker(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """PostToolUse/Skill: track skill usage to Core API."""
    return call_external_script(
        os.path.join(MEMVAULT_SCRIPTS, "skill_tracker_v2.py"),
        input_data=raw_input,
        timeout=5,
    )


def progressive_extract(
    event_type: str, tool_name: str, tool_input: dict, raw_input: str
) -> HookResult:
    """PreCompact: async progressive memory extraction — fire-and-forget."""
    import tempfile

    from .base import HOME, run_background

    python = os.path.join(HOME, ".local", "bin", "python3")

    # Write input to temp file for background process
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", prefix="memvault-prog-", suffix=".json", dir="/tmp", delete=False
        ) as tmpf:
            tmpf.write(raw_input)
            tmpfile_path = tmpf.name
    except Exception:
        return HookResult()

    script = os.path.join(MEMVAULT_SCRIPTS, "extract_progressive.py")
    if not os.path.isfile(script):
        return HookResult()

    # Background: cat input | python extract_progressive.py
    try:
        run_background(
            f"cat {tmpfile_path} | {python} {script}; rm -f {tmpfile_path}",
        )
    except Exception:
        # Cleanup temp file if background dispatch fails
        try:
            os.unlink(tmpfile_path)
        except OSError:
            pass
    return HookResult()


def sync_login(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """SessionStart: sync Playwright profile from master."""
    return call_external_script(
        os.path.join(HOME, ".playwright-profiles", "sync-login.sh") + " --hook",
        input_data=raw_input,
        timeout=15,
    )

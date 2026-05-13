"""
Shared foundation for all hook handlers.

Provides HookResult dataclass, convenience constructors, and common utilities
that replace the old hook-lib.sh boilerplate + duplicated patterns across
shell scripts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

HOME = os.path.expanduser("~")
HOOKS_DIR = os.path.join(HOME, ".claude", "hooks")
SKILLS_DIR = os.path.join(HOME, ".claude", "skills")


# ---------------------------------------------------------------------------
# Result type — every handler returns one of these
# ---------------------------------------------------------------------------


@dataclass
class HookResult:
    """Outcome of a single hook handler invocation."""

    decision: str | None = None  # "block", "approve", or None (passthrough)
    reason: str = ""
    message: str = ""
    text: str = ""  # Raw text for passthrough (UserPromptSubmit)
    updated_input: dict | None = None  # PreToolUse: rewrite tool_input

    def is_block(self) -> bool:
        return self.decision == "block"

    def is_approve(self) -> bool:
        return self.decision == "approve"


# Convenience constructors
ALLOW = HookResult()


def block(reason: str) -> HookResult:
    return HookResult(decision="block", reason=reason)


def approve() -> HookResult:
    return HookResult(decision="approve")


def message(msg: str) -> HookResult:
    return HookResult(message=msg)


def text_result(text: str) -> HookResult:
    return HookResult(text=text)


# ---------------------------------------------------------------------------
# Subprocess helpers (replace shell patterns)
# ---------------------------------------------------------------------------


def run_cmd(
    cmd: list[str] | str,
    input_data: str | None = None,
    timeout: int = 10,
    cwd: str | None = None,
) -> subprocess.CompletedProcess | None:
    """Run a subprocess safely. Returns None on any error."""
    try:
        return subprocess.run(
            cmd,
            shell=isinstance(cmd, str),
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except Exception:
        return None


def run_background(cmd: list[str] | str, cwd: str | None = None) -> subprocess.Popen | None:
    """Start a fire-and-forget background process (replaces `(cmd) &disown`)."""
    try:
        return subprocess.Popen(
            cmd,
            shell=isinstance(cmd, str),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=cwd,
        )
    except Exception:
        return None


def find_executable(name: str) -> str | None:
    """Find an executable in PATH (replaces `command -v`)."""
    return shutil.which(name)


# ---------------------------------------------------------------------------
# External handler wrapper (for scripts that live outside hook-observatory)
# ---------------------------------------------------------------------------


def call_external_script(
    command: str,
    input_data: str,
    timeout: int = 15,
) -> HookResult:
    """Run an external shell script, parse its output as a HookResult."""
    result = run_cmd(command, input_data=input_data, timeout=timeout)
    if result is None or not result.stdout.strip():
        return ALLOW

    raw = result.stdout.strip()
    try:
        parsed = json.loads(raw)
        return HookResult(
            decision=parsed.get("decision"),
            reason=parsed.get("reason", ""),
            message=parsed.get("message", ""),
        )
    except (json.JSONDecodeError, AttributeError):
        # Non-JSON output (e.g., recall text)
        return text_result(raw)

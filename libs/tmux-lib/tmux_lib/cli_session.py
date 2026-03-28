"""Interactive CLI session lifecycle management in tmux.

Detection, startup, prompt-wait, and shutdown for interactive CLI tools
(Claude Code, Gemini CLI, Codex CLI, etc.) running inside tmux panes.
All functions are free functions accepting a CLIProfile parameter.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from tmux_lib.primitives import (
    capture,
    capture_async,
    display,
    display_async,
    send_enter,
    send_enter_async,
    send_text,
    send_text_async,
    tmux_check,
    tmux_check_async,
)

if TYPE_CHECKING:
    from tmux_lib.patterns import CLIProfile

_SHELLS = frozenset({"zsh", "bash", "sh", "fish"})
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")

# ── Process detection ──


def get_pane_command(pane: str) -> str | None:
    """Get the current command running in a pane."""
    return display(pane, "#{pane_current_command}")


async def get_pane_command_async(pane: str) -> str | None:
    return await display_async(pane, "#{pane_current_command}")


def is_shell(pane: str) -> bool:
    """Check if pane is running a bare shell (no CLI tool)."""
    cmd = get_pane_command(pane)
    if not cmd:
        return True
    return cmd.split("/")[-1] in _SHELLS


async def is_shell_async(pane: str) -> bool:
    cmd = await get_pane_command_async(pane)
    if not cmd:
        return True
    return cmd.split("/")[-1] in _SHELLS


def is_process_running(pane: str, profile: CLIProfile) -> bool:
    """Check if a specific CLI tool is running (via pane_current_command + content fallback)."""
    cmd = get_pane_command(pane)
    if cmd:
        cmd_lower = cmd.lower()
        for name in profile.process_names:
            if name in cmd_lower:
                return True
        if cmd.split("/")[-1] in _SHELLS:
            return False
        if profile.detect_semver and _SEMVER_RE.match(cmd):
            return True
    if profile.content_indicators:
        content = capture(pane, start_line=-8)
        if content and profile.content_indicators.search(content):
            return True
    return False


async def is_process_running_async(pane: str, profile: CLIProfile) -> bool:
    cmd = await get_pane_command_async(pane)
    if cmd:
        cmd_lower = cmd.lower()
        for name in profile.process_names:
            if name in cmd_lower:
                return True
        if cmd.split("/")[-1] in _SHELLS:
            return False
        if profile.detect_semver and _SEMVER_RE.match(cmd):
            return True
    if profile.content_indicators:
        content = await capture_async(pane, start_line=-8)
        if content and profile.content_indicators.search(content):
            return True
    return False


# ── Prompt detection ──


def has_prompt(pane: str, profile: CLIProfile, *, lines: int = 5) -> bool:
    """Check if the CLI tool's idle prompt is visible."""
    bottom = capture(pane, start_line=-lines)
    if not bottom:
        return False
    return bool(profile.prompt_pattern.search(bottom))


async def has_prompt_async(pane: str, profile: CLIProfile, *, lines: int = 5) -> bool:
    bottom = await capture_async(pane, start_line=-lines)
    if not bottom:
        return False
    return bool(profile.prompt_pattern.search(bottom))


def is_busy(pane: str, profile: CLIProfile, *, lines: int = 8) -> bool:
    """Check if the CLI tool is actively processing (thinking/working)."""
    if not profile.processing_indicators:
        return False
    bottom = capture(pane, start_line=-lines)
    if not bottom:
        return False
    return bool(profile.processing_indicators.search(bottom))


async def is_busy_async(pane: str, profile: CLIProfile, *, lines: int = 8) -> bool:
    if not profile.processing_indicators:
        return False
    bottom = await capture_async(pane, start_line=-lines)
    if not bottom:
        return False
    return bool(profile.processing_indicators.search(bottom))


def wait_for_prompt(
    pane: str,
    profile: CLIProfile,
    *,
    timeout: int = 30,
    poll_interval: float = 2.0,
) -> bool:
    """Block until the CLI prompt appears. Returns True if found within timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if has_prompt(pane, profile):
            return True
        time.sleep(poll_interval)
    return False


async def wait_for_prompt_async(
    pane: str,
    profile: CLIProfile,
    *,
    timeout: int = 30,
    poll_interval: float = 2.0,
) -> bool:
    import asyncio as _aio

    deadline = time.time() + timeout
    while time.time() < deadline:
        if await has_prompt_async(pane, profile):
            return True
        await _aio.sleep(poll_interval)
    return False


# ── Generic text wait ──


def wait_for_text(
    pane: str,
    text: str,
    *,
    timeout: int = 30,
    poll_interval: float = 0.5,
    lines: int = 200,
) -> bool:
    """Wait for arbitrary text to appear in pane content."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        content = capture(pane, start_line=-lines, join_wrapped=True)
        if content and text in content:
            return True
        time.sleep(poll_interval)
    return False


# ── Startup ──


def start_cli(
    pane: str,
    command: str,
    profile: CLIProfile,
    *,
    wait_timeout: int = 30,
    poll_interval: float = 2.0,
    buf_name: str = "_ws_paste",
) -> bool:
    """Start a CLI tool in the pane and wait for its prompt.

    Only starts if the pane is currently a bare shell.
    Returns True if the CLI is ready (prompt visible).
    """
    if not is_shell(pane):
        return is_process_running(pane, profile)
    send_text(pane, command, buf_name=buf_name)
    send_enter(pane)
    return wait_for_prompt(pane, profile, timeout=wait_timeout, poll_interval=poll_interval)


async def start_cli_async(
    pane: str,
    command: str,
    profile: CLIProfile,
    *,
    wait_timeout: int = 30,
    poll_interval: float = 2.0,
    buf_name: str = "_ws_paste",
) -> bool:
    if not await is_shell_async(pane):
        return await is_process_running_async(pane, profile)
    await send_text_async(pane, command, buf_name=buf_name)
    await send_enter_async(pane)
    return await wait_for_prompt_async(
        pane, profile, timeout=wait_timeout, poll_interval=poll_interval
    )


# ── Shutdown ──


def shutdown_cli(pane: str, profile: CLIProfile, *, timeout: int = 15) -> bool:
    """Send exit command and wait for pane to return to shell."""
    send_text(pane, profile.exit_command)
    send_enter(pane)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_shell(pane):
            return True
        time.sleep(1)
    return False


async def shutdown_cli_async(
    pane: str, profile: CLIProfile, *, timeout: int = 15
) -> bool:
    import asyncio as _aio

    await send_text_async(pane, profile.exit_command)
    await send_enter_async(pane)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if await is_shell_async(pane):
            return True
        await _aio.sleep(1)
    return False

"""tmux primitive operations — sync and async subprocess wrappers.

Zero business logic. Pure tmux subprocess calls with consistent error handling.
Every sync function has an async counterpart with _async suffix.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass

# ── Result type ──


@dataclass(frozen=True, slots=True)
class TmuxResult:
    """Unified result from a tmux subprocess call."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


# ── Sync primitives ──


def tmux_run(*args: str, timeout: int = 10) -> TmuxResult:
    """Run a tmux command synchronously. Always returns TmuxResult (never raises)."""
    try:
        proc = subprocess.run(
            ["tmux", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return TmuxResult(proc.returncode, proc.stdout.strip(), proc.stderr.strip())
    except subprocess.TimeoutExpired:
        return TmuxResult(-1, "", f"timeout after {timeout}s")
    except FileNotFoundError:
        return TmuxResult(-2, "", "tmux binary not found")


def tmux_check(*args: str, timeout: int = 10) -> str:
    """Run a tmux command, raise RuntimeError on failure. Returns stdout."""
    r = tmux_run(*args, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"tmux {args[0]} failed (rc={r.returncode}): {r.stderr}")
    return r.stdout


def tmux_ok(*args: str, timeout: int = 10) -> str | None:
    """Run a tmux command, return stdout or None on failure."""
    r = tmux_run(*args, timeout=timeout)
    return r.stdout if r.ok else None


# ── Async primitives ──


async def tmux_run_async(*args: str, timeout: float = 10.0) -> TmuxResult:
    """Run a tmux command asynchronously. Always returns TmuxResult (never raises)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout)
        return TmuxResult(
            proc.returncode or 0,
            (stdout_b or b"").decode("utf-8", errors="replace").strip(),
            (stderr_b or b"").decode("utf-8", errors="replace").strip(),
        )
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return TmuxResult(-1, "", f"timeout after {timeout}s")


async def tmux_check_async(*args: str, timeout: float = 10.0) -> str:
    """Async: run tmux command, raise on failure."""
    r = await tmux_run_async(*args, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"tmux {args[0]} failed (rc={r.returncode}): {r.stderr}")
    return r.stdout


async def tmux_ok_async(*args: str, timeout: float = 10.0) -> str | None:
    """Async: run tmux command, return stdout or None."""
    r = await tmux_run_async(*args, timeout=timeout)
    return r.stdout if r.ok else None


# ── Convenience: display-message ──


def display(pane: str, fmt: str) -> str | None:
    """Query pane property via tmux display-message."""
    return tmux_ok("display-message", "-t", pane, "-p", fmt)


async def display_async(pane: str, fmt: str) -> str | None:
    return await tmux_ok_async("display-message", "-t", pane, "-p", fmt)


# ── Convenience: capture-pane ──


def capture(
    pane: str,
    *,
    start_line: int = -200,
    join_wrapped: bool = False,
    escape_sequences: bool = False,
) -> str | None:
    """Capture pane content.

    Args:
        start_line: negative = relative to bottom (default -200)
        join_wrapped: -J flag, join wrapped lines into logical lines
        escape_sequences: -e flag, include escape sequences
    """
    args = ["capture-pane", "-t", pane, "-p", "-S", str(start_line)]
    if join_wrapped:
        args.append("-J")
    if escape_sequences:
        args.append("-e")
    return tmux_ok(*args)


async def capture_async(
    pane: str,
    *,
    start_line: int = -200,
    join_wrapped: bool = False,
    escape_sequences: bool = False,
) -> str | None:
    args = ["capture-pane", "-t", pane, "-p", "-S", str(start_line)]
    if join_wrapped:
        args.append("-J")
    if escape_sequences:
        args.append("-e")
    return await tmux_ok_async(*args)


# ── Convenience: send-keys with ARG_MAX protection ──

_SEND_KEYS_LIMIT = 512


def send_text(
    pane: str, text: str, *, literal: bool = True, buf_name: str = "_ws_paste"
) -> None:
    """Send text to pane. Auto-switches to paste-buffer for text > 512 chars.

    Args:
        buf_name: unique buffer name per caller to avoid conflicts.
    """
    if literal and len(text) > _SEND_KEYS_LIMIT:
        _paste_text_sync(pane, text, buf_name)
        return
    args = ["send-keys", "-t", pane]
    if literal:
        args.append("-l")
    args.append(text)
    tmux_check(*args)


async def send_text_async(
    pane: str, text: str, *, literal: bool = True, buf_name: str = "_ws_paste"
) -> None:
    if literal and len(text) > _SEND_KEYS_LIMIT:
        await _paste_text_async(pane, text, buf_name)
        return
    args = ["send-keys", "-t", pane]
    if literal:
        args.append("-l")
    args.append(text)
    await tmux_check_async(*args)


def send_enter(pane: str) -> None:
    """Send Enter key to a pane."""
    tmux_check("send-keys", "-t", pane, "Enter")


async def send_enter_async(pane: str) -> None:
    await tmux_check_async("send-keys", "-t", pane, "Enter")


# ── Internal: paste-buffer (long text) ──


def _paste_text_sync(pane: str, text: str, buf_name: str) -> None:
    try:
        subprocess.run(
            ["tmux", "load-buffer", "-b", buf_name, "-"],
            input=text,
            text=True,
            capture_output=True,
            timeout=5,
            check=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        raise RuntimeError(f"tmux load-buffer failed: {e}") from e
    try:
        tmux_check("paste-buffer", "-b", buf_name, "-t", pane, "-d", "-p")
    except RuntimeError:
        tmux_ok("delete-buffer", "-b", buf_name)
        raise


async def _paste_text_async(pane: str, text: str, buf_name: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "tmux",
        "load-buffer",
        "-b",
        buf_name,
        "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate(input=text.encode())
    if proc.returncode != 0:
        raise RuntimeError(f"tmux load-buffer failed for {pane}")
    try:
        await tmux_check_async("paste-buffer", "-b", buf_name, "-t", pane, "-d", "-p")
    except RuntimeError:
        await tmux_ok_async("delete-buffer", "-b", buf_name)
        raise

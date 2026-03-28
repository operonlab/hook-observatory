#!/usr/bin/env python3
"""Run Claude Code (claude CLI) reliably on macOS.

Default mode is *auto*:
- If the prompt contains slash commands (lines starting with '/'),
  start an interactive session in tmux.
- Otherwise run headless (-p) through macOS BSD `script(1)` for a pseudo-terminal.

Why this wrapper exists:
- Claude Code can hang when run without a TTY.
- CI / automation environments are often non-interactive.
- macOS BSD `script` has different syntax from Linux GNU `script`.

macOS-specific features:
- BSD `script -q /dev/null cmd args...` (not Linux `script -q -c "cmd" /dev/null`)
- Desktop notifications via osascript
- Clipboard integration via pbcopy / pbpaste
- $TMPDIR for temp files (not /tmp)

Docs: https://code.claude.com/docs/en/headless
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from tmux_lib.cli_session import wait_for_text
from tmux_lib.primitives import capture, tmux_check, tmux_ok

DEFAULT_CLAUDE = os.environ.get(
    "CLAUDE_CODE_BIN",
    os.path.expanduser("~/.local/bin/claude"),
)
DEFAULT_LOG_DIR = os.path.expanduser("~/.claude/logs/headless")


def which(name: str) -> str | None:
    """Find an executable on PATH."""
    for p in os.environ.get("PATH", "").split(":"):
        cand = Path(p) / name
        try:
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
        except OSError:
            pass
    return None


def looks_like_slash_commands(prompt: str | None) -> bool:
    """Detect if prompt contains interactive slash commands."""
    if not prompt:
        return False
    return any(line.strip().startswith("/") for line in prompt.splitlines())


def notify_macos(title: str, message: str) -> None:
    """Send a macOS desktop notification via osascript."""
    try:
        script = f'display notification "{message}" with title "{title}"'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass


def copy_to_clipboard(text: str) -> None:
    """Copy text to macOS clipboard via pbcopy."""
    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(input=text.encode("utf-8"), timeout=5)
    except Exception:
        pass


def build_headless_cmd(args: argparse.Namespace) -> list[str]:
    """Build the claude CLI command for headless mode."""
    cmd: list[str] = [args.claude_bin]

    if args.permission_mode:
        cmd += ["--permission-mode", args.permission_mode]
    if args.prompt is not None:
        cmd += ["-p", args.prompt]
    if args.allowed_tools:
        cmd += ["--allowedTools", args.allowed_tools]
    if args.output_format:
        cmd += ["--output-format", args.output_format]
    if args.json_schema:
        cmd += ["--json-schema", args.json_schema]
    if args.append_system_prompt:
        cmd += ["--append-system-prompt", args.append_system_prompt]
    if args.system_prompt:
        cmd += ["--system-prompt", args.system_prompt]
    if args.continue_latest:
        cmd.append("--continue")
    if args.resume:
        cmd += ["--resume", args.resume]
    if args.extra:
        cmd += args.extra

    return cmd


def run_background(cmd: list[str], cwd: str | None, log_dir: str, notify: bool = False) -> int:
    """Run a command in the background via nohup, returning immediately.

    Writes stdout/stderr to a timestamped log file and prints the PID
    and log path so the caller can monitor progress later.
    """
    os.makedirs(log_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    log_file = os.path.join(log_dir, f"claude-{timestamp}.log")

    with open(log_file, "w") as lf:
        lf.write(f"# Command: {' '.join(shlex.quote(c) for c in cmd)}\n")
        lf.write(f"# Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        lf.write(f"# CWD: {cwd or os.getcwd()}\n\n")
        lf.flush()

        script_bin = which("script")
        if script_bin:
            full_cmd = [script_bin, "-q", "/dev/null"] + cmd
        else:
            full_cmd = cmd

        proc = subprocess.Popen(
            full_cmd,
            cwd=cwd,
            stdout=lf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    print("Background process started:")
    print(f"  PID:  {proc.pid}")
    print(f"  Log:  {log_file}")
    print(f"  Tail: tail -f {shlex.quote(log_file)}")
    print(f"  Stop: kill {proc.pid}")

    if notify:
        # Spawn a watcher that sends a notification when the process exits
        watcher_script = (
            f"while kill -0 {proc.pid} 2>/dev/null; do sleep 2; done; "
            f'osascript -e \'display notification "Background task finished (PID {proc.pid})" '
            f'with title "Claude Code"\''
        )
        subprocess.Popen(
            ["bash", "-c", watcher_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    return 0


def run_with_pty(cmd: list[str], cwd: str | None) -> int:
    """Run a command with a pseudo-terminal via macOS BSD script(1).

    macOS syntax:  script -q /dev/null cmd arg1 arg2 ...
    Linux syntax:  script -q -c "cmd arg1 arg2" /dev/null  (DO NOT use on macOS)
    """
    script_bin = which("script")
    if not script_bin:
        # Fallback: run directly without PTY
        proc = subprocess.run(cmd, cwd=cwd)
        return proc.returncode

    # macOS BSD: script -q /dev/null <command> [args...]
    full_cmd = [script_bin, "-q", "/dev/null"] + cmd
    proc = subprocess.run(full_cmd, cwd=cwd)
    return proc.returncode


# --- tmux interactive mode ---


def run_interactive_tmux(args: argparse.Namespace) -> int:
    """Start Claude Code interactively inside a tmux session."""
    if not which("tmux"):
        print("Error: tmux not found. Install via: brew install tmux", file=sys.stderr)
        return 2

    session = args.tmux_session
    target = f"{session}:0.0"

    # Kill existing session if any
    tmux_ok("kill-session", "-t", session)
    tmux_check("new", "-d", "-s", session, "-n", "claude")

    cwd = args.cwd or os.getcwd()

    # Build the claude launch command
    claude_parts = [args.claude_bin]
    if args.permission_mode:
        claude_parts += ["--permission-mode", args.permission_mode]
    if args.allowed_tools:
        claude_parts += ["--allowedTools", args.allowed_tools]
    if args.append_system_prompt:
        claude_parts += ["--append-system-prompt", args.append_system_prompt]
    if args.system_prompt:
        claude_parts += ["--system-prompt", args.system_prompt]
    if args.continue_latest:
        claude_parts.append("--continue")
    if args.resume:
        claude_parts += ["--resume", args.resume]
    if args.extra:
        claude_parts += args.extra

    launch = f"cd {shlex.quote(cwd)} && " + " ".join(shlex.quote(p) for p in claude_parts)
    tmux_check("send-keys", "-t", target, "-l", "--", launch)
    tmux_check("send-keys", "-t", target, "Enter")

    # Handle workspace trust prompt
    if wait_for_text(target, "Yes, I trust this folder", timeout=20):
        tmux_ok("send-keys", "-t", target, "Enter")
        time.sleep(0.8)
        if wait_for_text(target, "Yes, I trust this folder", timeout=2):
            tmux_ok("send-keys", "-t", target, "1")
            tmux_ok("send-keys", "-t", target, "Enter")

    # Send prompt lines
    if args.prompt:
        for line in (ln for ln in args.prompt.splitlines() if ln.strip()):
            tmux_check("send-keys", "-t", target, "-l", "--", line)
            tmux_check("send-keys", "-t", target, "Enter")
            time.sleep(args.interactive_send_delay_ms / 1000.0)

    print(f"Interactive Claude Code started in tmux session: {session}")
    print(f"  Attach:   tmux attach -t {shlex.quote(session)}")
    print(f"  Snapshot: tmux capture-pane -p -J -t {shlex.quote(target)} -S -200")

    # Optional: wait and snapshot
    if args.interactive_wait_s > 0:
        time.sleep(args.interactive_wait_s)
        snap = capture(target, start_line=-200, join_wrapped=True)
        if snap is not None:
            print("\n--- tmux snapshot (last 200 lines) ---\n")
            print(snap)

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run Claude Code reliably on macOS (headless or interactive via tmux)"
    )

    ap.add_argument(
        "-p",
        "--prompt",
        help="Prompt text. Headless: passed via -p. Interactive: sent as keystrokes.",
    )
    ap.add_argument(
        "--mode",
        choices=["auto", "headless", "interactive"],
        default="auto",
        help="Execution mode. 'auto' switches to interactive when prompt contains slash commands.",
    )
    ap.add_argument(
        "--permission-mode",
        default=None,
        help="Claude Code permission mode (plan, acceptEdits, bypassPermissions, etc.)",
    )
    ap.add_argument(
        "--allowedTools",
        dest="allowed_tools",
        help="Tool allowlist string (e.g. 'Bash,Read,Edit')",
    )
    ap.add_argument(
        "--output-format",
        dest="output_format",
        choices=["text", "json", "stream-json"],
        help="Output format (headless mode only)",
    )
    ap.add_argument("--json-schema", dest="json_schema", help="JSON schema for typed output")
    ap.add_argument(
        "--append-system-prompt",
        dest="append_system_prompt",
        help="Append to Claude Code default system prompt",
    )
    ap.add_argument(
        "--system-prompt",
        dest="system_prompt",
        help="Replace the system prompt entirely",
    )
    ap.add_argument(
        "--continue",
        dest="continue_latest",
        action="store_true",
        help="Continue the most recent conversation",
    )
    ap.add_argument("--resume", help="Resume a specific session ID")
    ap.add_argument(
        "--claude-bin",
        default=DEFAULT_CLAUDE,
        help=f"Path to claude binary (default: {DEFAULT_CLAUDE}). Or set CLAUDE_CODE_BIN env var.",
    )
    ap.add_argument("--cwd", help="Working directory (defaults to current directory)")
    ap.add_argument(
        "--notify",
        action="store_true",
        help="Send a macOS desktop notification on completion",
    )
    ap.add_argument(
        "--clipboard",
        action="store_true",
        help="Copy output to macOS clipboard via pbcopy",
    )

    # background options
    ap.add_argument(
        "--background",
        "--bg",
        action="store_true",
        help="Run in background (non-blocking). Returns immediately with PID and log path.",
    )
    ap.add_argument(
        "--log-dir",
        default=DEFAULT_LOG_DIR,
        help=f"Directory for background log files (default: {DEFAULT_LOG_DIR})",
    )

    # tmux options
    ap.add_argument("--tmux-session", default="claude-code", help="tmux session name")
    ap.add_argument(
        "--interactive-wait-s",
        type=int,
        default=0,
        help="Wait N seconds then print a tmux output snapshot",
    )
    ap.add_argument(
        "--interactive-send-delay-ms",
        type=int,
        default=800,
        help="Delay (ms) between sending lines in interactive mode",
    )

    ap.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip resource pre-flight checks (memory/context)",
    )
    ap.add_argument(
        "extra", nargs=argparse.REMAINDER, help="Extra args passed to claude (after --)"
    )

    args = ap.parse_args()

    # Strip leading '--' from extra args
    extra = args.extra
    if extra and extra[0] == "--":
        extra = extra[1:]
    args.extra = extra

    # Resolve claude binary
    if not Path(args.claude_bin).exists():
        # Try which as fallback
        found = which("claude")
        if found:
            args.claude_bin = found
        else:
            print(f"Error: claude binary not found at {args.claude_bin}", file=sys.stderr)
            print("Install: npm install -g @anthropic-ai/claude-code", file=sys.stderr)
            print("Or set CLAUDE_CODE_BIN=/path/to/claude", file=sys.stderr)
            return 2

    # Pre-flight resource check
    _shared = os.path.join(os.path.dirname(__file__), "..", "..", "_shared")
    if os.path.isdir(_shared) and not args.skip_preflight:
        sys.path.insert(0, _shared)
        try:
            from preflight import enforce_preflight

            enforce_preflight(force=False)
        except (ImportError, SystemExit) as exc:
            if isinstance(exc, SystemExit):
                return exc.code
        finally:
            if _shared in sys.path:
                sys.path.remove(_shared)

    # Determine mode
    mode = args.mode
    if mode == "auto" and looks_like_slash_commands(args.prompt):
        mode = "interactive"

    if args.background and mode != "interactive":
        cmd = build_headless_cmd(args)
        return run_background(cmd, cwd=args.cwd, log_dir=args.log_dir, notify=args.notify)

    if mode == "interactive":
        rc = run_interactive_tmux(args)
    else:
        cmd = build_headless_cmd(args)
        if args.clipboard:
            # Capture output for clipboard
            proc = subprocess.run(
                ["script", "-q", "/dev/null"] + cmd,
                cwd=args.cwd,
                capture_output=True,
                text=True,
            )
            print(proc.stdout, end="")
            if proc.stderr:
                print(proc.stderr, end="", file=sys.stderr)
            copy_to_clipboard(proc.stdout)
            rc = proc.returncode
        else:
            rc = run_with_pty(cmd, cwd=args.cwd)

    # Optional notification
    if args.notify:
        status = "completed" if rc == 0 else f"failed (exit {rc})"
        notify_macos("Claude Code", f"Headless task {status}")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())

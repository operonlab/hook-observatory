#!/usr/bin/env python3
"""Run Google Gemini CLI (gemini) reliably on macOS.

Default mode is *auto*:
- If the prompt contains slash commands (lines starting with '/'),
  start an interactive session in tmux.
- Otherwise run headless (-p) through macOS BSD `script(1)` for a pseudo-terminal.

Why this wrapper exists:
- Gemini CLI can hang when run without a TTY.
- CI / automation environments are often non-interactive.
- macOS BSD `script` has different syntax from Linux GNU `script`.

macOS-specific features:
- BSD `script -q /dev/null cmd args...` (not Linux `script -q -c "cmd" /dev/null`)
- Desktop notifications via osascript
- Clipboard integration via pbcopy / pbpaste
- $TMPDIR for temp files (not /tmp)

Docs: https://github.com/google-gemini/gemini-cli
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from tmux_lib.primitives import capture, tmux_check, tmux_ok

DEFAULT_GEMINI = os.environ.get("GEMINI_CLI_BIN", "")
DEFAULT_LOG_DIR = os.path.expanduser("~/.claude/logs/headless")
AGENT_METRICS_URL = os.environ.get(
    "AGENT_METRICS_URL", "http://127.0.0.1:10103/api/agent-metrics/ingest"
)

# Gemini pricing per 1M tokens (approximate, updated 2025-Q1)
_GEMINI_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00, "thinking": 1.25},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60, "thinking": 0.15},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
}


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


def resolve_gemini_bin(explicit: str) -> str | None:
    """Resolve the gemini binary path."""
    if explicit and Path(explicit).exists():
        return explicit
    for name in ("gemini",):
        found = which(name)
        if found:
            return found
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


# --- Metrics reporting helpers ---


def _estimate_cost(model_id: str, tokens: dict) -> float:
    """Estimate USD cost from Gemini token counts."""
    pricing = _GEMINI_PRICING.get("gemini-2.5-flash")  # fallback
    for key, rates in _GEMINI_PRICING.items():
        if key in (model_id or ""):
            pricing = rates
            break
    cost = 0.0
    inp = tokens.get("inputTokens", tokens.get("input_tokens", 0))
    out = tokens.get("outputTokens", tokens.get("output_tokens", 0))
    think = tokens.get("thinkingTokens", tokens.get("thinking_tokens", 0))
    cost += inp * pricing.get("input", 0) / 1_000_000
    cost += out * pricing.get("output", 0) / 1_000_000
    cost += think * pricing.get("thinking", pricing.get("input", 0)) / 1_000_000
    return round(cost, 6)


def _short_model_name(model_id: str) -> str:
    """Create short display name for Gemini model."""
    m = (model_id or "").lower()
    if "2.5-pro" in m:
        return "G2.5P"
    if "2.5-flash" in m:
        return "G2.5F"
    if "2.0-flash-lite" in m:
        return "G2.0FL"
    if "2.0-flash" in m:
        return "G2.0F"
    return (model_id or "gemini")[:8]


def _parse_gemini_stats(output: str) -> dict | None:
    """Try to parse Gemini JSON output for stats."""
    import json
    import re

    # Strip ANSI escape codes from script(1) typescript
    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", output)
    clean = re.sub(r"\r", "", clean)

    # Try parsing the whole thing as JSON
    try:
        data = json.loads(clean.strip())
        if isinstance(data, dict):
            return data.get("stats") or data
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to find last JSON object in the output (Gemini may print text then JSON)
    json_blocks = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", clean)
    for block in reversed(json_blocks):
        try:
            data = json.loads(block)
            if isinstance(data, dict) and (
                "stats" in data
                or "models" in data
                or "inputTokens" in data
                or "totalTokens" in data
            ):
                return data.get("stats", data)
        except (json.JSONDecodeError, ValueError):
            continue

    return None


def _report_to_agent_metrics(model_id: str, stats: dict | None, project: str = "") -> None:
    """POST metrics to agent-metrics service. Best-effort, never raises."""
    import hashlib
    import json
    from urllib.request import Request, urlopen

    try:
        tokens: dict = {}
        if stats:
            models = stats.get("models", {})
            for model_stats in models.values():
                tokens = model_stats.get("tokens", {})
                break
            if not tokens:
                tokens = stats.get("tokens", stats)

        inp = tokens.get("inputTokens", tokens.get("input_tokens", 0))
        out = tokens.get("outputTokens", tokens.get("output_tokens", 0))
        cost = _estimate_cost(model_id, tokens)
        sid = hashlib.md5(f"gemini-{time.time()}".encode()).hexdigest()[:8]

        payload = {
            "sid": sid,
            "cli": "gemini",
            "cost": cost,
            "model_id": model_id or "gemini-2.5-flash",
            "model_display": _short_model_name(model_id),
            "project": project,
            "context": {
                "input_tokens": inp,
                "output_tokens": out,
                "window_size": 1_000_000,
                "used_pct": 0,
            },
        }

        req = Request(
            AGENT_METRICS_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urlopen(req, timeout=2)
    except Exception:
        pass


def _run_headless_with_capture(cmd: list[str], cwd: str | None) -> tuple[int, str]:
    """Run with PTY, capturing output to temp file for metrics parsing.

    Uses macOS BSD script(1) to provide a PTY (real-time display) while
    simultaneously saving the typescript to a temp file for post-hoc parsing.
    """
    import tempfile

    script_bin = which("script")
    if not script_bin:
        proc = subprocess.run(cmd, cwd=cwd)
        return proc.returncode, ""

    fd, log_path = tempfile.mkstemp(suffix=".gemini.log")
    os.close(fd)

    try:
        full_cmd = [script_bin, "-q", log_path] + cmd
        proc = subprocess.run(full_cmd, cwd=cwd)
        captured = ""
        try:
            captured = Path(log_path).read_text(errors="replace")
        except Exception:
            pass
        return proc.returncode, captured
    finally:
        try:
            os.unlink(log_path)
        except OSError:
            pass


def build_headless_cmd(args: argparse.Namespace) -> list[str]:
    """Build the gemini CLI command for headless mode."""
    cmd: list[str] = [args.gemini_bin]

    if args.prompt is not None:
        cmd += ["-p", args.prompt]
    if args.model:
        cmd += ["-m", args.model]
    if args.output_format:
        cmd += ["--output-format", args.output_format]
    if args.approval_mode:
        cmd += ["--approval-mode", args.approval_mode]
    if args.yolo:
        cmd.append("--yolo")
    if args.allowed_tools:
        cmd += ["--allowed-tools", args.allowed_tools]
    if args.sandbox:
        cmd.append("--sandbox")
    if args.extensions:
        cmd += ["-e"] + args.extensions
    if args.include_directories:
        cmd += ["--include-directories", args.include_directories]
    if args.debug:
        cmd.append("--debug")
    if args.extra:
        cmd += args.extra

    return cmd


def run_background(cmd: list[str], cwd: str | None, log_dir: str, notify: bool = False) -> int:
    """Run a command in the background (non-blocking), returning immediately.

    Writes stdout/stderr to a timestamped log file and prints the PID
    and log path so the caller can monitor progress later.
    """
    os.makedirs(log_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    log_file = os.path.join(log_dir, f"gemini-{timestamp}.log")

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
        watcher_script = (
            f"while kill -0 {proc.pid} 2>/dev/null; do sleep 2; done; "
            f'osascript -e \'display notification "Background task finished (PID {proc.pid})" '
            f'with title "Gemini CLI"\''
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
        proc = subprocess.run(cmd, cwd=cwd)
        return proc.returncode

    full_cmd = [script_bin, "-q", "/dev/null"] + cmd
    proc = subprocess.run(full_cmd, cwd=cwd)
    return proc.returncode


# --- tmux interactive mode ---


def run_interactive_tmux(args: argparse.Namespace) -> int:
    """Start Gemini CLI interactively inside a tmux session."""
    if not which("tmux"):
        print("Error: tmux not found. Install via: brew install tmux", file=sys.stderr)
        return 2

    session = args.tmux_session
    target = f"{session}:0.0"

    # Kill existing session if any
    tmux_ok("kill-session", "-t", session)
    tmux_check("new", "-d", "-s", session, "-n", "gemini")

    cwd = args.cwd or os.getcwd()

    # Build the gemini launch command (interactive mode, no -p)
    gemini_parts = [args.gemini_bin]
    if args.model:
        gemini_parts += ["-m", args.model]
    if args.approval_mode:
        gemini_parts += ["--approval-mode", args.approval_mode]
    if args.yolo:
        gemini_parts.append("--yolo")
    if args.allowed_tools:
        gemini_parts += ["--allowed-tools", args.allowed_tools]
    if args.sandbox:
        gemini_parts.append("--sandbox")
    if args.extensions:
        gemini_parts += ["-e"] + args.extensions
    if args.debug:
        gemini_parts.append("--debug")
    if args.extra:
        gemini_parts += args.extra

    launch = f"cd {shlex.quote(cwd)} && " + " ".join(shlex.quote(p) for p in gemini_parts)
    tmux_check("send-keys", "-t", target, "-l", "--", launch)
    tmux_check("send-keys", "-t", target, "Enter")

    # Wait for gemini to be ready
    time.sleep(3)

    # Send prompt lines
    if args.prompt:
        for line in (ln for ln in args.prompt.splitlines() if ln.strip()):
            tmux_check("send-keys", "-t", target, "-l", "--", line)
            tmux_check("send-keys", "-t", target, "Enter")
            time.sleep(args.interactive_send_delay_ms / 1000.0)

    print(f"Interactive Gemini CLI started in tmux session: {session}")
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
        description="Run Google Gemini CLI reliably on macOS (headless or interactive via tmux)"
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
        "-m",
        "--model",
        default=None,
        help="Model to use (e.g. gemini-2.5-flash, gemini-2.5-pro)",
    )
    ap.add_argument(
        "--output-format",
        dest="output_format",
        choices=["text", "json", "stream-json"],
        help="Output format (headless mode only)",
    )
    ap.add_argument(
        "--approval-mode",
        dest="approval_mode",
        choices=["default", "auto_edit", "yolo", "plan"],
        default=None,
        help="Tool approval mode",
    )
    ap.add_argument(
        "-y",
        "--yolo",
        action="store_true",
        help="Auto-approve all tool calls (deprecated, use --approval-mode=yolo)",
    )
    ap.add_argument(
        "--allowed-tools",
        dest="allowed_tools",
        help="Comma-separated tools that bypass confirmation",
    )
    ap.add_argument(
        "-s",
        "--sandbox",
        action="store_true",
        help="Enable sandbox mode (Docker-based isolation)",
    )
    ap.add_argument(
        "-e",
        "--extensions",
        nargs="+",
        default=None,
        help="Extensions to use (-e none to disable all)",
    )
    ap.add_argument(
        "--include-directories",
        dest="include_directories",
        default=None,
        help="Additional directories in the workspace",
    )
    ap.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug/verbose output",
    )
    ap.add_argument(
        "--gemini-bin",
        default=DEFAULT_GEMINI,
        help="Path to gemini binary. Or set GEMINI_CLI_BIN env var.",
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
    ap.add_argument("--tmux-session", default="gemini-cli", help="tmux session name")
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
        "extra", nargs=argparse.REMAINDER, help="Extra args passed to gemini (after --)"
    )

    args = ap.parse_args()

    # Strip leading '--' from extra args
    extra = args.extra
    if extra and extra[0] == "--":
        extra = extra[1:]
    args.extra = extra

    # Resolve gemini binary
    resolved = resolve_gemini_bin(args.gemini_bin)
    if not resolved:
        print("Error: gemini binary not found.", file=sys.stderr)
        print("Install: npm install -g @google/gemini-cli", file=sys.stderr)
        print("Or set GEMINI_CLI_BIN=/path/to/gemini", file=sys.stderr)
        return 2
    args.gemini_bin = resolved

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
        captured = ""
        if args.clipboard:
            proc = subprocess.run(
                ["script", "-q", "/dev/null"] + cmd,
                cwd=args.cwd,
                capture_output=True,
                text=True,
            )
            captured = proc.stdout or ""
            print(captured, end="")
            if proc.stderr:
                print(proc.stderr, end="", file=sys.stderr)
            copy_to_clipboard(captured)
            rc = proc.returncode
        else:
            rc, captured = _run_headless_with_capture(cmd, args.cwd)

        # Report metrics to agent-metrics service (best-effort)
        project = Path(args.cwd).name if args.cwd else Path.cwd().name
        stats = _parse_gemini_stats(captured) if captured else None
        _report_to_agent_metrics(
            model_id=args.model or "gemini-2.5-flash",
            stats=stats,
            project=project,
        )

    # Optional notification
    if args.notify:
        status = "completed" if rc == 0 else f"failed (exit {rc})"
        notify_macos("Gemini CLI", f"Headless task {status}")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())

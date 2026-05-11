"""
Session Channel auto-announce handler.

Events:
  SessionStart  → publish 'sessions' join + 'agents' announce
  PreToolUse    → publish 'agents' heartbeat (30s throttled per pane)
  Stop          → publish 'sessions' done + 'agents' heartbeat (debounced)
  SessionEnd    → publish 'agents' leave

Fire-and-forget HTTP POST to session-channel station (localhost:10101).
Fails silently if station is not running.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time

from .base import ALLOW, HookResult, run_background
from .hook_config import get_service

_BASE_URL = get_service("session_channel_url")
_LOCAL_KEY = "change-me-in-production"
_DEBOUNCE_FILE = "/tmp/session-channel-stop-debounce-{pane}.ts"  # noqa: S108
_DEBOUNCE_SECONDS = 60
_HEARTBEAT_FILE = "/tmp/agent-hb-{pane}.ts"  # noqa: S108
_HEARTBEAT_SECONDS = 30
_CTX_BRIDGE_FILE = "/tmp/.claude-statusline/ctx-{pane_safe}.json"  # noqa: S108
_CTX_FRESH_SECONDS = 30


def _pane_id() -> str:
    pane = os.environ.get("TMUX_PANE", "")
    return pane.replace("%", "pane-") if pane else f"pid-{os.getpid()}"


def _pane_safe() -> str:
    pane = os.environ.get("TMUX_PANE", "")
    return pane.replace("%", "") if pane else f"p{os.getpid()}"


def _hostname() -> str:
    try:
        return socket.gethostname().split(".")[0]
    except OSError:
        return "?"


def _read_task_state() -> str:
    pane = os.environ.get("TMUX_PANE", "")
    if not pane:
        return ""
    state_file = f"/tmp/claude-task-{pane.replace('%', '')}.txt"  # noqa: S108
    try:
        return open(state_file).read().strip()
    except (FileNotFoundError, PermissionError):
        return ""


def _read_ctx_bridge() -> dict:
    """Read context % / model from statusline.sh's bridge file (30s freshness)."""
    path = _CTX_BRIDGE_FILE.format(pane_safe=_pane_safe())
    try:
        with open(path) as f:
            data = json.load(f)
        if time.time() - float(data.get("ts", 0)) > _CTX_FRESH_SECONDS:
            return {}
        return data
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        return {}


def _git_branch(cwd: str) -> str:
    if not cwd or not os.path.isdir(os.path.join(cwd, ".git")):
        return ""
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return "detached"


def _detect_role() -> str:
    """A relay-pending marker means this pane is acting as a worker."""
    pane_safe = _pane_safe()
    if os.path.isfile(f"/tmp/relay-pending-{pane_safe}.channel"):  # noqa: S108
        return "worker"
    return os.environ.get("CC_PANE_ROLE", "main")


def _parse_raw(raw_input: str) -> dict:
    try:
        return json.loads(raw_input) if raw_input else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _collect_agent_meta(raw_input: str) -> dict:
    """Aggregate everything we know about the current pane into a snapshot dict."""
    parsed = _parse_raw(raw_input)
    cwd = (
        parsed.get("cwd")
        or (parsed.get("workspace") or {}).get("current_dir")
        or (parsed.get("tool_input") or {}).get("cwd")
        or os.getcwd()
    )
    ctx = _read_ctx_bridge()
    pane_env = os.environ.get("TMUX_PANE", "")
    return {
        "v": 1,
        "host": _hostname(),
        "pane": pane_env or f"pid-{os.getpid()}",
        "sid": (parsed.get("session_id") or "")[:8],
        "cli": "claude",
        "model": ctx.get("model") or (parsed.get("model") or {}).get("id") or "",
        "role": _detect_role(),
        "branch": _git_branch(cwd) if cwd else "",
        "cwd": cwd.replace(os.path.expanduser("~"), "~") if cwd else "",
        "ctx_pct": ctx.get("pct"),
        "task": _read_task_state(),
        "ts": int(time.time()),
    }


def _send_async(
    topic: str,
    text: str,
    priority: str = "normal",
    tag: str = "",
    meta: dict | None = None,
) -> None:
    """Fire-and-forget POST to session-channel. Non-blocking."""
    body = {
        "topic": topic,
        "text": text,
        "sender": _pane_id(),
        "priority": priority,
    }
    if tag:
        body["tag"] = tag
    if meta:
        body["_meta"] = meta

    cmd = (
        f"curl -s -o /dev/null -m 2 -X POST {_BASE_URL}/api/messages "
        f"-H 'Content-Type: application/json' "
        f"-H 'x-local-key: {_LOCAL_KEY}' "
        f"-d {json.dumps(json.dumps(body))}"
    )
    run_background(cmd)


def _publish_agent_snapshot(tag: str, raw_input: str) -> None:
    """Build a one-line summary + structured meta and post to `agents` topic."""
    meta = _collect_agent_meta(raw_input)
    bits = [f"{meta['cli']}/{meta['role']}"]
    if meta.get("branch"):
        bits.append(f"on {meta['branch']}")
    if meta.get("ctx_pct") is not None:
        try:
            bits.append(f"ctx {float(meta['ctx_pct']):.0f}%")
        except (TypeError, ValueError):
            pass
    if meta.get("task"):
        bits.append(meta["task"][:48])
    text = " · ".join(bits) or f"{meta['cli']} {tag}"
    _send_async("agents", text, tag=tag, meta=meta)


def _stop_debounced() -> bool:
    pane = _pane_id()
    path = _DEBOUNCE_FILE.format(pane=pane)
    now = time.time()
    try:
        ts = float(open(path).read().strip())
        if now - ts < _DEBOUNCE_SECONDS:
            return True
    except (FileNotFoundError, ValueError):
        pass
    try:
        with open(path, "w") as f:
            f.write(str(now))
    except OSError:
        pass
    return False


def _heartbeat_throttled() -> bool:
    """Return True if we should SKIP this heartbeat (within throttle window)."""
    path = _HEARTBEAT_FILE.format(pane=_pane_id())
    now = time.time()
    try:
        ts = float(open(path).read().strip())
        if now - ts < _HEARTBEAT_SECONDS:
            return True
    except (FileNotFoundError, ValueError, OSError):
        pass
    try:
        with open(path, "w") as f:
            f.write(str(now))
    except OSError:
        pass
    return False


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """Handle SessionStart / PreToolUse / Stop / SessionEnd events."""

    if event_type == "SessionStart":
        cwd = ""
        try:
            parsed = json.loads(raw_input)
            cwd = parsed.get("tool_input", {}).get("cwd", "") or parsed.get("cwd", "")
        except (json.JSONDecodeError, AttributeError):
            pass
        short_cwd = cwd.replace(os.path.expanduser("~"), "~") if cwd else "?"
        _send_async("sessions", f"joined — {short_cwd}", tag="start")
        _publish_agent_snapshot("announce", raw_input)
        return ALLOW

    if event_type == "PreToolUse":
        if _heartbeat_throttled():
            return ALLOW
        _publish_agent_snapshot("heartbeat", raw_input)
        return ALLOW

    if event_type == "Stop":
        if _stop_debounced():
            return ALLOW

        task = _read_task_state()
        if task:
            relay_meta = ""
            pane = os.environ.get("TMUX_PANE", "")
            if pane:
                pane_safe = pane.replace("%", "")
                if os.path.isfile(f"/tmp/relay-pending-{pane_safe}.channel"):  # noqa: S108
                    relay_meta = f" [relay:%{pane_safe}]"
            _send_async("sessions", f"done: {task}{relay_meta}", tag="stop")
        _publish_agent_snapshot("heartbeat", raw_input)
        return ALLOW

    if event_type == "SessionEnd":
        _publish_agent_snapshot("leave", raw_input)
        return ALLOW

    return ALLOW

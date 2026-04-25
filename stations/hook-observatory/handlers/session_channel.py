"""
Session Channel auto-announce handler.

Events:
  SessionStart → announce session join to 'sessions' topic
  Stop         → announce session activity to 'sessions' topic (debounced)

Fire-and-forget HTTP POST to session-channel station (localhost:10101).
Fails silently if station is not running.
"""

from __future__ import annotations

import json
import os
import shlex
import time
from pathlib import Path

from .base import ALLOW, HookResult, run_background, run_cmd
from .hook_config import get_service

_BASE_URL = get_service("session_channel_url")
_LOCAL_KEY = "change-me-in-production"
_DEBOUNCE_FILE = "/tmp/session-channel-stop-debounce-{pane}.ts"  # noqa: S108
_DEBOUNCE_SECONDS = 60  # Don't announce Stop more than once per minute per pane

# --- Capability advertise (W1-A) ---
_MCPPROXY_CONFIG = Path.home() / ".mcpproxy" / "mcp_config.json"
_SKILLS_DIR = Path.home() / ".claude" / "skills"
_SKILLS_CACHE_TTL = 60  # seconds — process-wide cache
_skills_cache: tuple[float, list[str]] = (0.0, [])


def _pane_id() -> str:
    pane = os.environ.get("TMUX_PANE", "")
    return pane.replace("%", "pane-") if pane else f"pid-{os.getpid()}"


def _send_async(topic: str, text: str, priority: str = "normal", tag: str = "") -> None:
    """Fire-and-forget POST to session-channel. Non-blocking."""
    body = {
        "topic": topic,
        "text": text,
        "sender": _pane_id(),
        "priority": priority,
    }
    if tag:
        body["tag"] = tag

    # Use curl for fire-and-forget (no Python dependency on httpx in hook env)
    cmd = (
        f"curl -s -o /dev/null -m 2 -X POST {_BASE_URL}/api/messages "
        f"-H 'Content-Type: application/json' "
        f"-H 'x-local-key: {_LOCAL_KEY}' "
        f"-d '{json.dumps(body)}'"
    )
    run_background(cmd)


def _detect_cli_type() -> str:
    """Detect CLI from tmux pane_current_command via cli-rosetta."""
    pane = os.environ.get("TMUX_PANE", "")
    if not pane:
        return "unknown"
    result = run_cmd(
        ["tmux", "display-message", "-p", "-t", pane, "#{pane_current_command}"],
        timeout=2,
    )
    if not result or result.returncode != 0:
        return "unknown"
    cmd = result.stdout.strip()
    if not cmd:
        return "unknown"
    try:
        from cli_rosetta import detect_from_command  # type: ignore
    except ImportError:
        # cli-rosetta not on path — fall back to basename heuristic
        basename = cmd.split("/")[-1].lower()
        for token in ("claude", "codex", "gemini", "copilot", "qwen"):
            if token in basename:
                return f"{token}-code" if token in ("claude", "qwen") else f"{token}-cli"
        return "unknown"
    entry = detect_from_command(cmd)
    return entry.name if entry else "unknown"


def _read_mcps() -> list[str]:
    """Read MCP server names from ~/.mcpproxy/mcp_config.json."""
    try:
        data = json.loads(_MCPPROXY_CONFIG.read_text())
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        return []
    servers = data.get("mcpServers") or {}
    return sorted(servers.keys()) if isinstance(servers, dict) else []


def _read_skills() -> list[str]:
    """List ~/.claude/skills/ first-level directory names. Cached 60s."""
    global _skills_cache
    now = time.time()
    cached_ts, cached = _skills_cache
    if now - cached_ts < _SKILLS_CACHE_TTL and cached:
        return cached
    try:
        names = sorted(
            p.name for p in _SKILLS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")
        )
    except (FileNotFoundError, PermissionError):
        names = []
    _skills_cache = (now, names)
    return names


def _advertise_pane() -> None:
    """Fire-and-forget POST /api/panes/advertise."""
    now = int(time.time())
    payload = {
        "pane_id": _pane_id(),
        "cli_type": _detect_cli_type(),
        "mcps": _read_mcps(),
        "skills": _read_skills(),
        "started_at": now,
        "last_seen": now,
    }
    cmd = (
        f"curl -s -o /dev/null -m 2 -X POST {_BASE_URL}/api/panes/advertise "
        f"-H 'Content-Type: application/json' "
        f"-H 'x-local-key: {_LOCAL_KEY}' "
        f"-d {shlex.quote(json.dumps(payload))}"
    )
    run_background(cmd)


def _release_pane() -> None:
    """Fire-and-forget DELETE /api/panes/{pane_id}. Graceful on station down."""
    cmd = (
        f"curl -s -o /dev/null -m 2 -X DELETE "
        f"{_BASE_URL}/api/panes/{_pane_id()} "
        f"-H 'x-local-key: {_LOCAL_KEY}'"
    )
    run_background(cmd)


def _release_pane_pending() -> None:
    """Release all pending board tasks claimed by this pane.

    For every entry returned by ``GET /api/panes/{pane_id}/pending`` (which
    scans all active boards via ``XPENDING``), POST ``/api/board/<id>/drop``
    so the entry is force-claimed for ``__reaper`` and re-published by the
    W2-B reaper loop. Avoids zombie claims that would otherwise wait out the
    full lease window before being recycled.

    Independent of the 60s SessionStop debounce — task release MUST run on
    every Stop, even when message announcements are throttled.

    Discovery uses a short blocking ``urllib.request`` GET (2s timeout); the
    drop calls are dispatched fire-and-forget via ``curl`` so the hook never
    blocks pane teardown. All errors are swallowed — if the station is down,
    the reaper's lease-based fallback (~90s) still recovers the tasks.
    """
    pane_id = _pane_id()
    try:
        url = f"{_BASE_URL}/api/panes/{pane_id}/pending"
        req = urllib.request.Request(url, headers={"x-local-key": _LOCAL_KEY})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
    except Exception:
        return  # station down or network error — reaper lease-based fallback handles it

    for item in data.get("pending") or []:
        board_id = item.get("board_id")
        task_id = item.get("task_id")
        if not board_id or not task_id:
            continue
        body = json.dumps({"task_id": task_id, "pane": pane_id})
        try:
            subprocess.Popen(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-m",
                    "2",
                    "-X",
                    "POST",
                    f"{_BASE_URL}/api/board/{board_id}/drop",
                    "-H",
                    "Content-Type: application/json",
                    "-H",
                    f"x-local-key: {_LOCAL_KEY}",
                    "-d",
                    body,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            continue  # one bad task shouldn't stop the rest


def _read_task_state() -> str:
    """Read the current task description from the voice state file."""
    pane = os.environ.get("TMUX_PANE", "")
    if not pane:
        return ""
    state_file = f"/tmp/claude-task-{pane.replace('%', '')}.txt"  # noqa: S108
    try:
        return open(state_file).read().strip()
    except (FileNotFoundError, PermissionError):
        return ""


def _stop_debounced() -> bool:
    """Check if Stop was already announced recently for this pane."""
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


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """Handle SessionStart and Stop events."""

    if event_type == "SessionStart":
        # Parse session info from raw_input
        cwd = ""
        try:
            parsed = json.loads(raw_input)
            cwd = parsed.get("tool_input", {}).get("cwd", "")
        except (json.JSONDecodeError, AttributeError):
            pass

        short_cwd = cwd.replace(os.path.expanduser("~"), "~") if cwd else "?"
        _send_async("sessions", f"joined — {short_cwd}", tag="start")
        # Capability advertise — independent of message debounce
        _advertise_pane()
        return ALLOW

    if event_type == "Stop":
        # W2-C: release any board tasks this pane still has pending FIRST,
        # so they can be re-dispatched while capability is still advertised.
        # Independent of the 60s message debounce.
        _release_pane_pending()
        # Then drop the capability advertisement itself.
        _release_pane()

        if _stop_debounced():
            return ALLOW

        task = _read_task_state()
        if task:
            # Detect relay pane — pending file exists when relay is waiting
            relay_meta = ""
            pane = os.environ.get("TMUX_PANE", "")
            if pane:
                pane_safe = pane.replace("%", "")
                if os.path.isfile(f"/tmp/relay-pending-{pane_safe}.channel"):  # noqa: S108
                    relay_meta = f" [relay:%{pane_safe}]"
            _send_async("sessions", f"done: {task}{relay_meta}", tag="stop")
        return ALLOW

    return ALLOW

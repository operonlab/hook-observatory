"""
Context Relay handler — seamless session handoff via session-channel.

Events:
  SessionStart → check for pending handoff, inject into system reminder
  PreCompact   → advisory: suggest `handoff spawn` when context is being compacted
"""

from __future__ import annotations

import json
import os
import re
import time

from .base import ALLOW, HookResult, message, run_cmd

_BASE_URL = "http://localhost:10101"
_LOCAL_KEY = os.environ.get("SESSION_CHANNEL_KEY", "change-me-in-production")
_HANDOFF_DIR = "/tmp/handoff"  # noqa: S108
_PANE_RE = re.compile(r"^pane-\d+$")
_HANDOFF_TTL = 300  # 5 minutes — reject stale file fallbacks to avoid pane-number reuse bugs


def _pane_id() -> str:
    """Return normalised pane identifier (e.g. 'pane-42'). Empty if not in tmux."""
    pane = os.environ.get("TMUX_PANE", "")
    if not pane:
        return ""
    pid = pane.replace("%", "pane-")
    # Whitelist: only pane-<digits> allowed (prevents shell injection)
    return pid if _PANE_RE.match(pid) else ""


def _pane_num() -> str:
    """Return raw pane number (e.g. '42'). Empty if not in tmux."""
    pane = os.environ.get("TMUX_PANE", "")
    if not pane:
        return ""
    num = pane.replace("%", "")
    return num if num.isdigit() else ""


def _read_from_redis(pane: str) -> dict | None:
    """Read latest handoff from session-channel. Returns parsed message or None.

    Fetches up to 50 messages and takes the last (newest, since xrange is chronological).
    """
    topic = f"handoff:{pane}"
    # Use list form to avoid shell=True (security: no shell injection)
    result = run_cmd(
        [
            "curl",
            "-s",
            "-m",
            "3",
            f"{_BASE_URL}/api/messages/{topic}?count=50",
            "-H",
            f"x-local-key: {_LOCAL_KEY}",
        ],
        timeout=5,
    )
    if result is None or result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        msgs = data.get("messages", [])
        if not msgs:
            return None
        # xrange returns oldest-first → take last for newest
        return msgs[-1]
    except (json.JSONDecodeError, KeyError, IndexError):
        return None


def _consume_redis_topic(pane: str) -> None:
    """Delete the handoff topic from Redis after consumption.

    Uses XTRIM to set maxlen=0, effectively clearing all messages.
    Fire-and-forget — failure is acceptable (TTL will clean up eventually).
    """
    topic = f"handoff:{pane}"
    # POST an empty trim request — send a "consumed" marker that will trigger trim
    # Simplest: just send a consume marker, the 30min TTL handles the rest
    # Actually: use redis-cli XTRIM directly via session-channel isn't exposed,
    # so we write a "consumed" tag message that makes the topic stale
    run_cmd(
        [
            "curl",
            "-s",
            "-o",
            "/dev/null",
            "-m",
            "2",
            "-X",
            "POST",
            f"{_BASE_URL}/api/messages",
            "-H",
            "Content-Type: application/json",
            "-H",
            f"x-local-key: {_LOCAL_KEY}",
            "-d",
            json.dumps(
                {
                    "topic": topic,
                    "text": "__consumed__",
                    "sender": pane,
                    "tag": "consumed",
                }
            ),
        ],
        timeout=3,
    )


def _read_from_file(pane_num: str) -> dict | None:
    """Read handoff from file fallback. Returns parsed JSON or None.

    Rejects files older than _HANDOFF_TTL to prevent stale handoffs from
    being injected when tmux reuses a pane number.
    """
    if not pane_num.isdigit():
        return None
    path = os.path.join(_HANDOFF_DIR, f"{pane_num}.json")
    try:
        with open(path) as f:
            data = json.load(f)
        # TTL check: reject stale handoffs (guards against pane number reuse)
        ts = data.get("timestamp", 0)
        if isinstance(ts, (int, float)) and ts > 0:
            if time.time() - ts > _HANDOFF_TTL:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
                return None
        return data
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return None


def _cleanup_handoff(pane: str, pane_num: str) -> None:
    """Remove consumed handoff from both file and Redis."""
    # File cleanup
    if pane_num.isdigit():
        path = os.path.join(_HANDOFF_DIR, f"{pane_num}.json")
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    # Redis cleanup — mark topic as consumed
    _consume_redis_topic(pane)


def _format_handoff(handoff_md: str, source: str, ts_str: str, role: str | None = None) -> str:
    """Format handoff content for system reminder injection."""
    age = ""
    try:
        ts = float(ts_str) if ts_str else 0
        if ts > 0:
            delta = int(time.time() - ts)
            if delta < 60:
                age = f"{delta} 秒前"
            elif delta < 3600:
                age = f"{delta // 60} 分鐘前"
            else:
                age = f"{delta // 3600} 小時前"
    except (ValueError, TypeError):
        pass

    header = f"[Context Relay] 接續自 {source} 的工作"
    if age:
        header += f"（{age}）"
    if role:
        header += f"\n**角色**: {role}"

    return f"{header}\n\n{handoff_md}"


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """Handle SessionStart (consume handoff) and PreCompact (advisory)."""

    if event_type == "SessionStart":
        pane = _pane_id()
        pane_num = _pane_num()
        if not pane or not pane_num:
            return ALLOW

        # Priority 1: Redis (session-channel)
        redis_msg = _read_from_redis(pane)
        if redis_msg:
            text = redis_msg.get("text", "")
            tag = redis_msg.get("tag", "")
            # Skip consumed markers
            if text and tag != "consumed" and text != "__consumed__":
                _cleanup_handoff(pane, pane_num)
                # Redis text is pre-formatted by handoff CLI's _format_for_injection
                return message(text)

        # Priority 2: File fallback
        file_data = _read_from_file(pane_num)
        if file_data:
            handoff_md = file_data.get("handoff_md", "")
            source = file_data.get("source_pane", "?")
            ts_str = str(file_data.get("timestamp", ""))
            role = file_data.get("role")
            if handoff_md:
                _cleanup_handoff(pane, pane_num)
                return message(_format_handoff(handoff_md, source, ts_str, role))

        return ALLOW

    if event_type == "PreCompact":
        return message("💡 Context 即將壓縮。如需完整交棒到新 session，可執行 `handoff spawn`")

    return ALLOW

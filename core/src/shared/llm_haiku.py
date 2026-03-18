"""Haiku extraction via dedicated tmux capture window.

A persistent Claude Code instance (--model haiku --dangerously-skip-permissions)
runs in tmux window ``capture``. Communication via send-keys + pane capture.
Redis cache (TTL=3600s) for dedup.

Idle watchdog: if no calls in 30 min, auto-recycle (see capture_watchdog.py).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import subprocess
import time

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ── Config ──
TMUX_TARGET = "capture"  # window name (index 3)
_CLAUDE_CMD = "CLAUDE_VOICE=0 claude --dangerously-skip-permissions --model haiku"
_SHELLS = {"zsh", "bash", "sh", "fish"}
_POLL_INTERVAL = 0.8
_TIMEOUT = 45  # seconds — interactive session can be slow on first turn
_CACHE_TTL = 3600
_REDIS_URL = "redis://localhost:6379/0"
_PROMPT_RE = re.compile(r"❯\s*$", re.MULTILINE)
_REDIS_LAST_USED_KEY = "capture:haiku:last_used"

_redis_pool = aioredis.ConnectionPool.from_url(_REDIS_URL, decode_responses=True)
_haiku_lock = asyncio.Lock()


# ── tmux self-healing ──


def _ensure_capture_window() -> bool:
    """Ensure tmux capture window exists with Claude Haiku running.

    Returns True if ready, False if unable to start.
    """
    # Check if capture window exists
    try:
        windows = _tmux("list-windows", "-F", "#{window_name}")
    except Exception:
        logger.warning("haiku: tmux not available")
        return False

    if TMUX_TARGET not in windows.split("\n"):
        # Create window at index 3
        logger.info("haiku: creating capture window")
        try:
            _tmux("new-window", "-t", ":3", "-n", TMUX_TARGET, check=True)
            time.sleep(1)
        except Exception:
            # Index 3 might be taken, try without index
            try:
                _tmux("new-window", "-n", TMUX_TARGET, check=True)
                time.sleep(1)
            except Exception:
                logger.warning("haiku: failed to create capture window")
                return False

    # Check if Claude is running (not a bare shell)
    cmd = _tmux("display-message", "-t", TMUX_TARGET, "-p", "#{pane_current_command}")
    is_shell = cmd.split("/")[-1] in _SHELLS

    if is_shell or not cmd:
        # Start Claude Haiku
        logger.info("haiku: starting Claude Haiku in capture window")
        _tmux("send-keys", "-t", TMUX_TARGET, "-l", _CLAUDE_CMD)
        _tmux("send-keys", "-t", TMUX_TARGET, "Enter")
        # Wait for ❯ prompt
        if not _wait_ready(timeout=30):
            logger.warning("haiku: Claude Haiku failed to start within 30s")
            return False
        logger.info("haiku: Claude Haiku ready")

    return True


# ── tmux primitives (sync, called via asyncio.to_thread) ──


def _tmux(*args: str, check: bool = False) -> str:
    proc = subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"tmux {args[0]} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _capture_pane(lines: int = 80) -> str:
    return _tmux("capture-pane", "-t", TMUX_TARGET, "-p", "-S", str(-lines))


_SEND_KEYS_LIMIT = 512


def _paste_text(pane: str, text: str) -> None:
    """Send long text via load-buffer + paste-buffer (no length limit)."""
    buf = "_haiku_paste"
    subprocess.run(
        ["tmux", "load-buffer", "-b", buf, "-"],
        input=text,
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )
    _tmux("paste-buffer", "-b", buf, "-t", pane, "-d", "-p")


def _send_prompt(text: str) -> None:
    """Send text + Enter to capture window.

    Short text (<512 chars): direct send-keys -l.
    Long text: load-buffer + paste-buffer to avoid truncation.
    """
    if len(text) > _SEND_KEYS_LIMIT:
        _paste_text(TMUX_TARGET, text)
    else:
        _tmux("send-keys", "-t", TMUX_TARGET, "-l", text)
    _tmux("send-keys", "-t", TMUX_TARGET, "Enter")


def _is_ready() -> bool:
    """Check if capture pane shows idle ❯ prompt."""
    bottom = _tmux("capture-pane", "-t", TMUX_TARGET, "-p", "-S", "-5")
    return bool(_PROMPT_RE.search(bottom))


def _wait_ready(timeout: int = _TIMEOUT) -> bool:
    """Poll until ❯ prompt appears (Haiku done responding)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_ready():
            return True
        time.sleep(_POLL_INTERVAL)
    return False


def _extract_json_from_output(output: str) -> dict | None:
    """Extract JSON object from pane output via brace-matching (supports nested)."""
    last_close = output.rfind("}")
    if last_close == -1:
        return None
    # Walk backward from last } to find matching {
    for start in range(last_close, -1, -1):
        if output[start] == "{":
            candidate = output[start : last_close + 1]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return None


def _sync_haiku_call(prompt: str, timeout: int = _TIMEOUT) -> dict | None:
    """Blocking: send prompt to tmux capture window, wait for stable output, extract JSON."""
    # Ensure ready
    if not _is_ready():
        logger.warning("haiku_extract: capture window not ready, waiting...")
        if not _wait_ready(timeout=15):
            logger.warning("haiku_extract: capture window not responding")
            return None

    # Snapshot pane BEFORE sending (to detect change)
    before_snapshot = _capture_pane(40)

    _send_prompt(prompt)

    # Phase 1: Wait for pane content to CHANGE (Haiku started processing)
    deadline = time.time() + timeout
    changed = False
    while time.time() < deadline:
        time.sleep(0.5)
        current = _capture_pane(40)
        if current != before_snapshot:
            changed = True
            break
    if not changed:
        logger.warning("haiku_extract: pane content never changed — Haiku may be stuck")
        return None

    # Phase 2: Wait for content to STABILIZE (Haiku done responding)
    # Content stops changing for 2 consecutive checks = done
    stable_count = 0
    last_content = current
    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)
        current = _capture_pane(40)
        if current == last_content:
            stable_count += 1
            if stable_count >= 2:
                break
        else:
            stable_count = 0
            last_content = current

    if stable_count < 2:
        logger.warning("haiku_extract: timed out waiting for stable output")
        return None

    # Phase 3: Extract JSON from NEW content only (diff from before)
    # Find content that wasn't in before_snapshot
    new_content = current
    for i, (a, b) in enumerate(zip(before_snapshot, current)):
        if a != b:
            new_content = current[i:]
            break
    else:
        # If before is a prefix of current, take the remainder
        if len(current) > len(before_snapshot):
            new_content = current[len(before_snapshot) :]

    result = _extract_json_from_output(new_content)
    if result is None:
        logger.warning("haiku_extract: no JSON found - %.300s", new_content[-300:])
    else:
        logger.info("haiku_extract: extracted %d fields", len(result))

    return result


# ── Public async API ──


def _cache_key(system: str, user_message: str, schema: dict) -> str:
    raw = system + "\x00" + user_message + "\x00" + json.dumps(schema, sort_keys=True)
    return f"capture:llm:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def _build_prompt(system: str, user_message: str, tool: dict) -> str:
    schema = tool.get("input_schema", {})
    props = schema.get("properties", {})
    field_desc = "\n".join(f"- {k}: {v.get('description', '')}" for k, v in props.items())
    return (
        f"{system}\n\n"
        f"## Fields to extract\n{field_desc}\n\n"
        f"## User input\n{user_message}\n\n"
        "Reply with ONLY a valid JSON object. No explanation, no markdown fences."
    )


async def haiku_extract(
    *,
    user_message: str,
    tool: dict,
    system: str = "",
) -> dict | None:
    """Send extraction request to persistent Haiku in tmux, return parsed dict or None.

    Uses asyncio.Lock to serialize access to the single tmux pane.
    Auto-heals the capture window if it doesn't exist or Claude isn't running.
    """
    cache_key = _cache_key(system, user_message, tool)

    # Cache read (outside lock — no tmux needed)
    try:
        r = aioredis.Redis(connection_pool=_redis_pool)
        cached = await r.get(cache_key)
        if cached:
            logger.info("haiku_extract: cache hit key=%s", cache_key)
            return json.loads(cached)
    except Exception as exc:
        logger.warning("haiku_extract: redis read error - %s", exc)

    # Serialize tmux access
    async with _haiku_lock:
        # Self-heal: ensure capture window + Claude Haiku are running
        ready = await asyncio.to_thread(_ensure_capture_window)
        if not ready:
            return None

        prompt = _build_prompt(system, user_message, tool)
        result = await asyncio.to_thread(_sync_haiku_call, prompt)

    if result is None:
        return None

    # Cache write + update last_used (outside lock)
    try:
        r = aioredis.Redis(connection_pool=_redis_pool)
        await r.setex(cache_key, _CACHE_TTL, json.dumps(result))
        await r.set(_REDIS_LAST_USED_KEY, str(int(time.time())))
    except Exception as exc:
        logger.warning("haiku_extract: redis write error - %s", exc)

    return result

"""
Read:Edit ratio monitor — detects blind-edit anti-pattern.

Tracks Read vs Edit/Write tool calls per session. When the model edits
files without reading them first, it signals shallow reasoning (the
"editing without reading" pattern identified in Laurenzo's 6,852-session
analysis).

Thresholds (from empirical data):
  - Good: read:edit ratio >= 4.0, blind edit rate < 10%
  - Warning: ratio < 3.0 OR blind edit rate > 25%
  - Alert: ratio < 2.0 OR blind edit rate > 35%

State: /tmp/.read-edit-ratio-{hash}.json (per-session, auto-cleaned)
Latency: <1ms (JSON read/write, no network)
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time

from .base import ALLOW, HookResult, message, run_background

# --- Bark config ---
_BARK_SERVER = "http://localhost:8090"
_BARK_DEVICE_KEY = "gx7KnK5f8iAKuqNLWzy5hP"

# --- Thresholds ---
_MIN_EDITS_FOR_WARN = 5  # Don't warn until enough data
_RATIO_WARN = 3.0  # read:edit ratio below this → warn
_RATIO_ALERT = 2.0  # below this → strong alert
_BLIND_WARN = 0.25  # blind edit rate above 25% → warn
_BLIND_ALERT = 0.35  # above 35% → strong alert
_WARN_COOLDOWN_S = 300  # 5 min between warnings


def _state_path(session_id: str) -> str:
    h = hashlib.sha256(session_id.encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f".read-edit-ratio-{h}.json")


def _load(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save(path: str, state: dict) -> None:
    try:
        with open(path, "w") as f:
            json.dump(state, f, separators=(",", ":"))
    except OSError:
        pass


def _extract_session_id(raw_input: str) -> str:
    try:
        parsed = json.loads(raw_input)
        return str(parsed.get("session_id", "")) or "default"
    except (json.JSONDecodeError, AttributeError):
        return "default"


def _extract_file_path(tool_input: dict) -> str:
    return tool_input.get("file_path", "")


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if event_type != "PostToolUse":
        return ALLOW

    # Only track Read, Edit, Write
    if tool_name not in ("Read", "Edit", "Write"):
        return ALLOW

    session_id = _extract_session_id(raw_input)
    sp = _state_path(session_id)
    state = _load(sp)

    if not state:
        state = {
            "reads": [],  # file paths that have been Read
            "read_count": 0,
            "edit_count": 0,
            "blind_edits": 0,
            "last_warn_at": 0,
            "started_at": time.time(),
        }

    file_path = _extract_file_path(tool_input)

    if tool_name == "Read":
        state["read_count"] = state.get("read_count", 0) + 1
        reads = state.get("reads", [])
        if file_path and file_path not in reads:
            reads.append(file_path)
            # Cap list size to avoid unbounded growth
            if len(reads) > 500:
                reads = reads[-500:]
        state["reads"] = reads
        _save(sp, state)
        return ALLOW

    # Edit or Write
    state["edit_count"] = state.get("edit_count", 0) + 1

    # Check if file was previously Read in this session
    reads = state.get("reads", [])
    if file_path and file_path not in reads:
        state["blind_edits"] = state.get("blind_edits", 0) + 1

    edit_count = state["edit_count"]
    read_count = state.get("read_count", 0)
    blind_edits = state.get("blind_edits", 0)

    _save(sp, state)

    # Not enough data yet
    if edit_count < _MIN_EDITS_FOR_WARN:
        return ALLOW

    # Calculate metrics
    ratio = read_count / edit_count if edit_count > 0 else float("inf")
    blind_rate = blind_edits / edit_count if edit_count > 0 else 0

    # Check cooldown
    now = time.time()
    if now - state.get("last_warn_at", 0) < _WARN_COOLDOWN_S:
        return ALLOW

    # Determine severity
    alert = False
    warn = False

    if ratio < _RATIO_ALERT or blind_rate > _BLIND_ALERT:
        alert = True
    elif ratio < _RATIO_WARN or blind_rate > _BLIND_WARN:
        warn = True

    if not alert and not warn:
        return ALLOW

    # Update cooldown
    state["last_warn_at"] = now
    _save(sp, state)

    severity = "🔴" if alert else "🟡"
    msg = (
        f"{severity} [read:edit ratio] "
        f"R:E={ratio:.1f} (目標≥4.0), "
        f"盲改率={blind_rate:.0%} ({blind_edits}/{edit_count}), "
        f"reads={read_count} edits={edit_count}"
    )

    if alert:
        msg += " — 模型可能進入淺思考模式, 建議重啟 session"

    # Push notifications (fire-and-forget, non-blocking)
    _notify(severity, ratio, blind_rate, alert)

    return message(msg)


def _notify(severity: str, ratio: float, blind_rate: float, is_alert: bool) -> None:
    """Send macOS notification + Bark push in background."""
    from urllib.parse import quote

    title = f"{severity} Read:Edit Ratio"
    body = f"R:E={ratio:.1f}, 盲改率={blind_rate:.0%}"
    if is_alert:
        body += " — 建議重啟 session"

    # macOS notification center
    osa_body = body.replace('"', '\\"')
    osa_title = title.replace('"', '\\"')
    run_background(
        f'osascript -e \'display notification "{osa_body}" '
        f'with title "{osa_title}" sound name "Sosumi"\''
    )

    # Bark push
    bark_url = (
        f"{_BARK_SERVER}/{_BARK_DEVICE_KEY}"
        f"/{quote(title)}/{quote(body)}"
        f"?group=hook-observatory&sound={'alarm' if is_alert else 'bell'}"
        f"&level={'timeSensitive' if is_alert else 'active'}"
    )
    run_background(["curl", "-sf", bark_url])

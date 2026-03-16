"""
Anvil telemetry — PostToolUse/Skill handler.

API-first, file-fallback: try synchronous POST to Anvil API first.
Only writes to local JSONL spool when API is unreachable.
SessionStart triggers background sync of any pending spool entries.

Latency: ~2-5ms when API is up (sync HTTP), <1ms fallback (file append).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

from .base import ALLOW, HookResult, run_background

ANVIL_API = os.environ.get("ANVIL_API", "http://127.0.0.1:4103")
SPOOL_DIR = os.path.join(os.path.expanduser("~"), ".claude", "data", "anvil-telemetry")
SPOOL_FILE = os.path.join(SPOOL_DIR, "pending.jsonl")


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """PostToolUse/Skill: API POST → file fallback.
    SessionStart: sync any pending spool entries."""
    if event_type == "SessionStart":
        return _sync_pending()

    if tool_name != "Skill":
        return ALLOW

    skill_name = tool_input.get("skill", "")
    if not skill_name:
        return ALLOW

    # Parse raw_input for session context + tool_response
    try:
        parsed = json.loads(raw_input) if raw_input.strip() else {}
    except (json.JSONDecodeError, AttributeError):
        parsed = {}

    data = parsed.get("data", parsed)
    tool_response = data.get("tool_response", {})

    payload = {
        "skill_name": skill_name,
        "session_id": data.get("session_id", ""),
        "agent_model": data.get("agent_model", ""),
        "tool_use_id": data.get("tool_use_id", ""),
        "success": tool_response.get("success", True),
        "error_message": tool_response.get("error", None),
        "tool_calls_count": 1,
        "payload": {
            "args": tool_input.get("args", ""),
            "cwd": data.get("cwd", ""),
        },
    }

    # --- API first ---
    if _post_to_api(payload):
        return ALLOW

    # --- File fallback (API unreachable) ---
    _write_spool(payload)
    return ALLOW


def _post_to_api(payload: dict) -> bool:
    """Synchronous POST to Anvil API. Returns True on success."""
    try:
        url = f"{ANVIL_API}/api/anvil/invocations"
        # Guard: only allow http/https — never file: or custom schemes (S310)
        if not url.startswith(("http://", "https://")):
            return False
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310
            return resp.status in (200, 201)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"[anvil-telemetry] API POST failed: {exc}", file=sys.stderr)
        return False


def _write_spool(payload: dict) -> None:
    """Append invocation to local JSONL spool. Never raises."""
    try:
        os.makedirs(SPOOL_DIR, exist_ok=True)
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "synced": False,
            **payload,
        }
        with open(SPOOL_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[anvil-telemetry] Spool write failed: {exc}", file=sys.stderr)


def _sync_pending() -> HookResult:
    """SessionStart: background sync any pending spool entries."""
    if not os.path.exists(SPOOL_FILE):
        return ALLOW
    try:
        with open(SPOOL_FILE) as f:
            has_pending = any(line.strip() for line in f)
        if has_pending:
            run_background(
                [
                    os.path.join(os.path.expanduser("~"), ".local", "bin", "python3"),
                    os.path.join(
                        os.path.expanduser("~"),
                        "workshop",
                        "stations",
                        "anvil",
                        "scripts",
                        "anvil_telemetry_sync.py",
                    ),
                ]
            )
    except OSError:
        pass
    return ALLOW

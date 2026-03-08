"""
Anvil telemetry — PostToolUse/Skill handler.

Captures skill invocations and sends them to the Anvil station API
for long-term tracking and analysis. Fire-and-forget: never blocks.
Latency: <1ms (background subprocess HTTP POST).
"""

from __future__ import annotations

import json
import os

from .base import ALLOW, HookResult, run_background

ANVIL_API = os.environ.get("ANVIL_API", "http://127.0.0.1:4103")


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """PostToolUse/Skill: record skill invocation to Anvil API."""
    if tool_name != "Skill":
        return ALLOW

    # Extract skill info from tool_input
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

    # Build invocation payload
    payload = {
        "skill_name": skill_name,
        "session_id": data.get("session_id", ""),
        "agent_model": data.get("agent_model", ""),
        "success": tool_response.get("success", True),
        "error_message": tool_response.get("error", None),
        "tool_calls_count": 1,
        "payload": {
            "args": tool_input.get("args", ""),
            "cwd": data.get("cwd", ""),
        },
    }

    # Fire-and-forget HTTP POST to Anvil API
    curl_cmd = [
        "curl",
        "-s",
        "-X",
        "POST",
        f"{ANVIL_API}/api/anvil/invocations",
        "-H",
        "Content-Type: application/json",
        "-d",
        json.dumps(payload, ensure_ascii=False),
        "--connect-timeout",
        "2",
        "--max-time",
        "5",
    ]
    run_background(curl_cmd)

    return ALLOW

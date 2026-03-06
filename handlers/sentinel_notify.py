"""
Sentinel auto-notify/resolve — paired lifecycle for service maintenance state.

PreToolUse:  detect service-modifying Bash commands → POST /notify
PostToolUse: same detection → POST /resolve (command completed)

This ensures MAINTENANCE state is always bounded by the actual command
execution window, preventing stale maintenance from accumulating.

Latency: <1ms (fire-and-forget background curl).
"""

from __future__ import annotations

import json
import os
import re

from .base import ALLOW, HookResult, run_background

_SENTINEL_BASE = "http://127.0.0.1:4101/api/sentinel"

# Patterns: (regex, service_hint)
PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"workshop-services\.sh\s+(restart|stop|start)"), "workshop-services"),
    (re.compile(r"docker\s+(restart|stop|start)\s+ws-infra"), "docker-infra"),
    (re.compile(r"uvicorn.*--port\s+880[0-9]"), "core"),
    (re.compile(r"kill\s.*880[1-9]|kill\s.*4100|kill\s.*8840"), "kill-service"),
    (re.compile(r"nginx\s+-s\s+(reload|stop|quit)"), "nginx"),
    (re.compile(r"pnpm\s+run\s+build"), "frontend-build"),
    (re.compile(r"docker\s+restart\s+ws-infra-postgres"), "postgres"),
    (re.compile(r"docker\s+restart\s+ws-infra-redis"), "redis"),
]


def _detect_service(command: str) -> str | None:
    """Match command against known service-modifying patterns."""
    for pattern, service in PATTERNS:
        if pattern.search(command):
            return service
    return None


def _fire(endpoint: str, payload: dict) -> None:
    """Fire-and-forget POST to sentinel via background curl. Never blocks."""
    run_background(
        [
            "curl",
            "-s",
            "-X",
            "POST",
            f"{_SENTINEL_BASE}/{endpoint}",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps(payload, ensure_ascii=False),
            "--connect-timeout",
            "2",
            "--max-time",
            "5",
        ],
    )


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """PreToolUse → notify, PostToolUse → resolve. Both for Bash only."""
    if tool_name != "Bash":
        return ALLOW

    command = tool_input.get("command", "")
    if not command:
        return ALLOW

    service = _detect_service(command)
    if not service:
        return ALLOW

    agent_id = os.environ.get("CLAUDE_SESSION_ID", "unknown-agent")

    if event_type == "PreToolUse":
        _fire(
            "notify",
            {
                "service": service,
                "action": command[:100],
                "agent_id": agent_id,
                "estimated_duration": 300,
            },
        )
    elif event_type == "PostToolUse":
        _fire(
            "resolve",
            {
                "service": service,
                "agent_id": agent_id,
                "result": "completed",
            },
        )

    return ALLOW

"""
Sentinel auto-notify — fire-and-forget POST to /api/sentinel/notify.

Detects service-modifying Bash commands and notifies sentinel
so it knows an agent is working and should suppress auto-intervention.

Latency: <5ms (non-blocking, 2s timeout).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from .base import ALLOW, HookResult

SENTINEL_URL = "http://127.0.0.1:4101/api/sentinel/notify"

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


def _fire_notify(service: str, action: str, agent_id: str) -> None:
    """Fire-and-forget POST to sentinel. Never blocks, never throws."""
    try:
        payload = json.dumps(
            {
                "service": service,
                "action": action,
                "agent_id": agent_id,
                "estimated_duration": 300,
            }
        ).encode()
        req = urllib.request.Request(
            SENTINEL_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except (urllib.error.URLError, OSError, Exception):
        pass  # Sentinel down or unreachable — never block agent


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """PreToolUse/Bash: detect service-modifying commands → auto POST /notify."""
    if tool_name != "Bash":
        return ALLOW

    command = tool_input.get("command", "")
    if not command:
        return ALLOW

    service = _detect_service(command)
    if not service:
        return ALLOW

    # Agent ID from env or session
    agent_id = os.environ.get("CLAUDE_SESSION_ID", "unknown-agent")
    _fire_notify(service, command[:100], agent_id)

    return ALLOW

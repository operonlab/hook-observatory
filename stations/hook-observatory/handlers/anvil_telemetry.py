"""
Anvil telemetry — multi-channel usage tracker.

Tracks three invocation channels:
  1. Skill tool calls (PostToolUse/Skill)
  2. MCP server calls (PostToolUse/mcp__mcpproxy__call_tool_*)
  3. CLI commands (PostToolUse/Bash) — known station CLIs only

API-first, file-fallback: try synchronous POST to Anvil API first.
Only writes to local JSONL spool when API is unreachable.
SessionStart triggers background sync of any pending spool entries.

Latency: ~2-5ms when API is up (match + HTTP), <0.01ms on non-match (dict lookup).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from .base import ALLOW, HookResult, run_background

ANVIL_API = os.environ.get("ANVIL_API", "http://127.0.0.1:10301")
SPOOL_DIR = os.path.join(os.path.expanduser("~"), ".claude", "data", "anvil-telemetry")
SPOOL_FILE = os.path.join(SPOOL_DIR, "pending.jsonl")

# ---------------------------------------------------------------------------
# Skill-level config
# ---------------------------------------------------------------------------

ALIAS_MAP = {
    "r": "prompt-router",
}

_TEST_PREFIXES = ("_", "test-")
_TEST_EXACT = {"test-skill", "test-verify", "general-purpose", "commit"}
_TEST_PATTERN_DIGITS = re.compile(r"^skill-\d+$")

# CLI builtins (not skills, skip intent tracking)
_CLI_BUILTINS = frozenset(
    {
        "clear",
        "exit",
        "context",
        "mcp",
        "login",
        "model",
        "config",
        "help",
        "compact",
        "fast",
        "cost",
        "memory",
        "permissions",
        "agents",
        "skills",
        "terminal-setup",
        "vim",
        "bug",
        "doctor",
        "release-notes",
        "init",
        "review",
        "allowed-tools",
        "listen",
        "status-bar",
        "add-dir",
        "loop",
    }
)

_COMMAND_NAME_RE = re.compile(r"<command-name>/([^<]+)</command-name>")

# ---------------------------------------------------------------------------
# Tool registry (loaded once at module level)
# ---------------------------------------------------------------------------

_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "tool_registry.json")

_MCP_REGISTRY: dict[str, str] = {}
_CLI_REGISTRY: dict[str, str] = {}

try:
    with open(_REGISTRY_PATH) as _f:
        _reg = json.load(_f)
    _MCP_REGISTRY = _reg.get("mcp_servers", {})
    _CLI_REGISTRY = _reg.get("cli_commands", {})
except (OSError, json.JSONDecodeError):
    pass

_MCP_PROXY_TOOLS = frozenset(
    {
        "mcp__mcpproxy__call_tool_read",
        "mcp__mcpproxy__call_tool_write",
        "mcp__mcpproxy__call_tool_destructive",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_test(name: str) -> bool:
    """Return True if this is a test/probe invocation that should not be tracked."""
    if any(name.startswith(p) for p in _TEST_PREFIXES):
        return True
    if name in _TEST_EXACT:
        return True
    if _TEST_PATTERN_DIGITS.match(name):
        return True
    return False


def _parse_context(raw_input: str) -> dict:
    """Extract session context from raw hook input."""
    try:
        parsed = json.loads(raw_input) if raw_input.strip() else {}
    except (json.JSONDecodeError, AttributeError):
        parsed = {}
    return parsed.get("data", parsed)


def _post_intent(payload: dict) -> None:
    """POST intent to Anvil API. Fire-and-forget, no spool."""
    try:
        url = f"{ANVIL_API}/api/anvil/intents"
        if not url.startswith(("http://", "https://")):
            return
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)  # noqa: S310
    except (urllib.error.URLError, OSError, ValueError):
        pass


def _send(payload: dict) -> None:
    """POST to Anvil API, fall back to spool on failure."""
    if _post_to_api(payload):
        return
    _write_spool(payload)


# ---------------------------------------------------------------------------
# Channel handlers
# ---------------------------------------------------------------------------


def _handle_intent(raw_input: str) -> HookResult:
    """UserPromptSubmit: extract <command-name> tags and POST intents."""
    matches = _COMMAND_NAME_RE.findall(raw_input)
    if not matches:
        return ALLOW

    session_id = ""
    try:
        parsed = json.loads(raw_input) if raw_input.strip().startswith("{") else {}
        data = parsed.get("data", parsed)
        session_id = data.get("session_id", "")
    except (json.JSONDecodeError, AttributeError):
        pass

    for skill_name in matches:
        skill_name = skill_name.strip()
        if skill_name in _CLI_BUILTINS:
            continue
        if _is_test(skill_name):
            continue
        _post_intent({"skill_name": skill_name, "session_id": session_id})

    return ALLOW


def _handle_skill(tool_input: dict, raw_input: str) -> HookResult:
    """Handle Skill tool invocations."""
    skill_name = tool_input.get("skill", "")
    if not skill_name:
        return ALLOW

    if _is_test(skill_name):
        return ALLOW

    original_name = None
    if skill_name in ALIAS_MAP:
        original_name = skill_name
        skill_name = ALIAS_MAP[skill_name]

    data = _parse_context(raw_input)
    tool_response = data.get("tool_response", {})

    payload_data: dict = {
        "args": tool_input.get("args", ""),
        "cwd": data.get("cwd", ""),
    }
    if original_name:
        payload_data["original_name"] = original_name

    _send(
        {
            "skill_name": skill_name,
            "session_id": data.get("session_id", ""),
            "agent_model": data.get("agent_model", ""),
            "tool_use_id": data.get("tool_use_id", ""),
            "success": tool_response.get("success", True),
            "error_message": tool_response.get("error", None),
            "tool_calls_count": 1,
            "category": "skill",
            "payload": payload_data,
        }
    )
    return ALLOW


def _handle_mcp(tool_input: dict, raw_input: str) -> HookResult:
    """Handle MCP proxy tool calls (call_tool_read/write/destructive)."""
    # tool_input.name = "tmux-relay:relay_run"
    mcp_name = tool_input.get("name", "")
    if ":" not in mcp_name:
        return ALLOW

    server_name, tool_name = mcp_name.split(":", 1)
    station = _MCP_REGISTRY.get(server_name)
    if not station:
        return ALLOW

    data = _parse_context(raw_input)

    _send(
        {
            "skill_name": station,
            "session_id": data.get("session_id", ""),
            "agent_model": data.get("agent_model", ""),
            "tool_use_id": data.get("tool_use_id", ""),
            "success": True,
            "tool_calls_count": 1,
            "category": "mcp",
            "payload": {
                "tool": tool_name,
                "server": server_name,
                "cwd": data.get("cwd", ""),
            },
        }
    )
    return ALLOW


def _handle_cli(tool_input: dict, raw_input: str) -> HookResult:
    """Handle Bash commands that match known station CLIs."""
    cmd = tool_input.get("command", "").strip()
    if not cmd:
        return ALLOW

    # Extract first token basename: "/Users/.../relay" → "relay"
    tokens = cmd.split(None, 2)  # split into max 3 parts
    if not tokens:
        return ALLOW

    binary = os.path.basename(tokens[0])
    station = _CLI_REGISTRY.get(binary)
    if not station:
        return ALLOW

    data = _parse_context(raw_input)
    subcommand = tokens[1] if len(tokens) > 1 else ""

    _send(
        {
            "skill_name": station,
            "session_id": data.get("session_id", ""),
            "agent_model": data.get("agent_model", ""),
            "tool_use_id": data.get("tool_use_id", ""),
            "success": True,
            "tool_calls_count": 1,
            "category": "cli",
            "payload": {
                "tool": subcommand,
                "command": cmd[:200],
                "cwd": data.get("cwd", ""),
            },
        }
    )
    return ALLOW


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    """Multi-channel telemetry handler.

    Routes to the appropriate channel handler based on tool_name.
    Non-matching tools return ALLOW immediately (<0.01ms).
    """
    if event_type == "SessionStart":
        return _sync_pending()

    if event_type == "UserPromptSubmit":
        return _handle_intent(raw_input)

    if tool_name == "Skill":
        return _handle_skill(tool_input, raw_input)

    if tool_name in _MCP_PROXY_TOOLS:
        return _handle_mcp(tool_input, raw_input)

    if tool_name == "Bash":
        return _handle_cli(tool_input, raw_input)

    return ALLOW


# ---------------------------------------------------------------------------
# API + spool (shared infrastructure)
# ---------------------------------------------------------------------------


def _post_to_api(payload: dict) -> bool:
    """Synchronous POST to Anvil API. Returns True on success."""
    try:
        url = f"{ANVIL_API}/api/anvil/invocations"
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

#!/usr/bin/env python3
"""Sandbox MCP Server — Thin wrapper over SandboxClient SDK.

2 tools: sandbox_execute + sandbox_info.
All logic lives in workshop.clients.sandbox (SDK layer).

Usage:
    python3 mcp/sandbox/server.py

Configure in ~/.claude.json:
    "sandbox-executor": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/sandbox/server.py"],
        "env": {
            "PYTHON_PATH": "/Users/joneshong/.local/bin/python3"
        }
    }
"""

import json
from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from sdk_client.sandbox import SandboxClient
from sdk_client.mcp_helpers import mcp_error_handler

mcp = FastMCP("sandbox-executor")
client = SandboxClient()


# ======================== Result Formatting ========================


def _format_result(result, description=None, max_output: int = 3000) -> str:
    max_stderr = max(max_output // 3, 500)  # stderr cap = 1/3 of stdout cap, min 500
    max_structured = max_output + 2000  # structured slightly higher than stdout

    parts = []
    if description:
        parts.append(f"## Task: {description}")

    parts.append(f"**Status**: {'Success' if result.success else 'Failed'}")
    parts.append(f"**Duration**: {result.duration_ms}ms")

    if result.timed_out:
        parts.append("**Execution timed out**")

    if result.stdout.strip():
        stdout = (
            result.stdout[:max_output] + f"\n... (truncated, {len(result.stdout)} total chars)"
            if len(result.stdout) > max_output
            else result.stdout
        )
        parts.append(f"\n### stdout\n```\n{stdout}\n```")

    if result.stderr.strip():
        stderr = (
            result.stderr[:max_stderr] + f"\n... (truncated, {len(result.stderr)} total chars)"
            if len(result.stderr) > max_stderr
            else result.stderr
        )
        parts.append(f"\n### stderr\n```\n{stderr}\n```")

    if result.outputs:
        parts.append("\n### Structured Outputs")
        for entry in result.outputs:
            if isinstance(entry, dict):
                label = entry.get("label", "")
                data = entry.get("data", entry)
            else:
                label = ""
                data = entry
            label_str = f"**{label}**\n" if label else ""
            data_str = (
                json.dumps(data, ensure_ascii=False, indent=2)
                if not isinstance(data, str)
                else data
            )
            truncated = (
                data_str[:max_structured] + f"\n... (truncated, {len(data_str)} total chars)"
                if len(data_str) > max_structured
                else data_str
            )
            parts.append(f"{label_str}```json\n{truncated}\n```")

    return "\n".join(parts)


# ======================== Tools ========================


@mcp.tool()
@mcp_error_handler("Sandbox")
async def sandbox_execute(
    language: str,
    code: str,
    timeout: int = 30,
    description: str = "",
    max_output: int = 3000,
) -> str:
    """Execute Python/JS code with auto-injected SDK helpers: http_get(), http_post(), read_file(), write_file(), output(). Use this to batch multiple operations into a single execution — read/write any file, call any HTTP endpoint, process data. Returns structured results via output(). Timeout: 30s default, 60s max."""
    max_output = min(max_output, 5000)
    result = await to_thread(client.execute, code, language, timeout)
    return _format_result(result, description or None, max_output=max_output)


@mcp.tool()
@mcp_error_handler("Sandbox")
async def sandbox_info(language: str = "python") -> str:
    """Show documentation for the sandbox SDK helpers (available functions, constraints, examples)."""
    return client.info(language)


# ======================== Main ========================

if __name__ == "__main__":
    mcp.run()

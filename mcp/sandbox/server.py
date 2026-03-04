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

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients.sandbox import SandboxClient

server = Server("sandbox-executor")
client = SandboxClient()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="sandbox_execute",
            description=(
                "Execute Python/JS code with auto-injected SDK helpers: "
                "http_get(), http_post(), read_file(), write_file(), output(). "
                "Use this to batch multiple operations into a single execution — "
                "read/write any file, call any HTTP endpoint, process data. "
                "Returns structured results via output(). "
                "Timeout: 30s default, 60s max."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "enum": ["python", "javascript"],
                        "description": "Programming language to execute",
                    },
                    "code": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "Code to execute in the sandbox. SDK helpers "
                            "(http_get, http_post, read_file, write_file, output) "
                            "are auto-injected."
                        ),
                    },
                    "timeout": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 60,
                        "default": 30,
                        "description": "Execution timeout in seconds (default: 30)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of what this code does (for logging)",
                    },
                },
                "required": ["language", "code"],
            },
        ),
        Tool(
            name="sandbox_info",
            description="Show documentation for the sandbox SDK helpers (available functions, constraints, examples).",
            inputSchema={
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "enum": ["python", "javascript"],
                        "default": "python",
                        "description": "Which language SDK to show docs for",
                    },
                },
            },
        ),
    ]


# ======================== Result Formatting ========================


def _format_result(result, description=None) -> str:
    parts = []
    if description:
        parts.append(f"## Task: {description}")

    parts.append(f"**Status**: {'Success' if result.success else 'Failed'}")
    parts.append(f"**Duration**: {result.duration_ms}ms")

    if result.timed_out:
        parts.append("**Execution timed out**")

    if result.stdout.strip():
        stdout = (
            result.stdout[:5000] + "\n... (truncated)"
            if len(result.stdout) > 5000
            else result.stdout
        )
        parts.append(f"\n### stdout\n```\n{stdout}\n```")

    if result.stderr.strip():
        stderr = (
            result.stderr[:2000] + "\n... (truncated)"
            if len(result.stderr) > 2000
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
            truncated = data_str[:8000] + "\n... (truncated)" if len(data_str) > 8000 else data_str
            parts.append(f"{label_str}```json\n{truncated}\n```")

    return "\n".join(parts)


# ======================== Tool Handler ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "sandbox_execute":
        language = arguments.get("language", "python")
        code = arguments.get("code", "")
        timeout = arguments.get("timeout", 30)
        description = arguments.get("description")

        result = await to_thread(client.execute, code, language, timeout)
        return text_result(_format_result(result, description))

    elif name == "sandbox_info":
        language = arguments.get("language", "python")
        return text_result(client.info(language))

    return text_result(f"Unknown tool: {name}")


# ======================== Main ========================


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

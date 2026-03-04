#!/Users/joneshong/.local/bin/python3
"""Session Redactor MCP Server — thin wrapper over SessionRedactorClient SDK.

5 tools:
    session_redactor_status    — aggregate stats (files, redactions, last run)
    session_redactor_sweep     — run full sweep of ~/.claude/projects/
    session_redactor_redact    — redact a single file by path
    session_redactor_patterns  — list all detection patterns
    session_redactor_history   — recent processing records

All logic lives in workshop.clients.session_redactor (SDK layer).

Usage:
    python3 mcp/session-redactor/server.py

Configure in ~/.claude.json:
    "session-redactor": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/session-redactor/server.py"],
        "env": {}
    }
"""

import asyncio
import json
import os
import sys
from asyncio import to_thread

# Allow importing from workshop package regardless of PYTHONPATH
_script_dir = os.path.dirname(os.path.abspath(__file__))
_workshop_libs = os.path.join(_script_dir, "..", "..", "libs", "python", "src")
if os.path.isdir(_workshop_libs) and _workshop_libs not in sys.path:
    sys.path.insert(0, _workshop_libs)

from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import TextContent, Tool  # noqa: E402
from workshop.clients.session_redactor import SessionRedactorClient  # noqa: E402

server = Server("workshop-session-redactor")
client = SessionRedactorClient()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def json_result(data) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="session_redactor_status",
            description=(
                "Get Session Redactor aggregate stats: total files processed, "
                "total redactions made, and last processing timestamp. "
                "Use this to understand how much sensitive data has been cleaned."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="session_redactor_sweep",
            description=(
                "Run a full sweep of all Claude session transcripts (~/.claude/projects/). "
                "Detects and redacts API keys, passwords, tokens, and other secrets. "
                "Returns count of files processed and total redactions made."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "trigger": {
                        "type": "string",
                        "description": "Reason for sweep (default: 'sweep')",
                        "default": "sweep",
                    },
                },
            },
        ),
        Tool(
            name="session_redactor_redact",
            description=(
                "Redact sensitive data from a single .jsonl transcript file. "
                "Parses JSON, recursively walks all string values, applies all "
                "16 detection patterns (API keys, passwords, tokens, AWS, SSH, etc.), "
                "and atomically writes the cleaned file back."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the .jsonl file to redact",
                    },
                    "trigger": {
                        "type": "string",
                        "description": "Trigger label for audit log (default: 'manual')",
                        "default": "manual",
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="session_redactor_patterns",
            description=(
                "List all sensitive data detection patterns with their names and categories. "
                "Categories include: password, api_key, token, aws_key, aws_secret, "
                "ssh_key, db_password, generic_secret."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="session_redactor_history",
            description=(
                "Get recent session transcript processing records. "
                "Shows which files were processed, how many redactions were made, "
                "and what triggered each processing run."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum records to return (default: 30)",
                        "default": 30,
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Filter by specific session ID (optional)",
                    },
                },
            },
        ),
    ]


# ======================== Tool Handlers ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "session_redactor_status":
            stats = await to_thread(client.get_stats)
            return json_result(stats)

        elif name == "session_redactor_sweep":
            trigger = arguments.get("trigger", "sweep")
            summary = await to_thread(client.full_sweep, trigger)
            return json_result(summary)

        elif name == "session_redactor_redact":
            file_path = arguments["file_path"]
            trigger = arguments.get("trigger", "manual")
            result = await to_thread(client.redact_file, file_path, trigger)
            return json_result(result.to_dict())

        elif name == "session_redactor_patterns":
            patterns = await to_thread(client.list_patterns)
            return json_result(patterns)

        elif name == "session_redactor_history":
            limit = arguments.get("limit", 30)
            session_id = arguments.get("session_id")
            if session_id:
                records = await to_thread(client.get_session_history, session_id)
            else:
                records = await to_thread(client.get_history, limit)
            return json_result(records)

        else:
            return text_result(f"Unknown tool: {name}")

    except Exception as e:
        return text_result(f"Error: {e}")


# ======================== Entry Point ========================


async def main():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

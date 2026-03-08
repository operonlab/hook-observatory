"""tmux-webui MCP Server -- tmux session management tools for Claude Code.

3 tools: tmux_webui_sessions, tmux_webui_relay, tmux_webui_autocomplete.

Usage (via .mcp.json):
    uv run --no-project --with 'mcp>=1.0' --with httpx python3 mcp/tmux-webui/server.py
"""

import asyncio
import json
from asyncio import to_thread

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients.tmux_webui import TmuxWebuiClient, TmuxWebuiError

server = Server("tmux-webui")
client = TmuxWebuiClient()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="tmux_webui_sessions",
            description=(
                "List tmux sessions with their windows and panes. "
                "Provides a complete view of the tmux environment."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session": {
                        "type": "string",
                        "description": "Session name to get details for (windows + panes). "
                        "If omitted, lists all sessions.",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "Max number of sessions/windows/panes to return",
                    },
                },
            },
        ),
        Tool(
            name="tmux_webui_relay",
            description=(
                "Dispatch a command to a tmux relay pane. "
                "Optionally poll for completion. Returns pane ID and signal file path."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command to dispatch to a relay pane",
                    },
                    "timeout": {
                        "type": "integer",
                        "default": 30,
                        "description": "Timeout in seconds for the relay command",
                    },
                    "wait": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, poll until command completes (up to timeout)",
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="tmux_webui_autocomplete",
            description="Get autocomplete suggestions for tmux commands, sessions, or paths.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The query string for autocomplete",
                    },
                    "type": {
                        "type": "string",
                        "description": "Filter by type (optional)",
                    },
                    "refresh": {
                        "type": "boolean",
                        "default": False,
                        "description": "Refresh autocomplete cache before querying",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "Max number of autocomplete suggestions to return",
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        match name:
            case "tmux_webui_sessions":
                session = arguments.get("session")
                limit = arguments.get("limit", 20)
                if session:
                    windows = await to_thread(client.list_windows, session)
                    panes = await to_thread(client.list_panes, session)
                    result = {
                        "session": session,
                        "total_windows": len(windows),
                        "total_panes": len(panes),
                        "windows": windows[:limit],
                        "panes": panes[:limit],
                    }
                else:
                    sessions = await to_thread(client.list_sessions)
                    total_count = len(sessions)
                    result = {
                        "total_count": total_count,
                        "items": sessions[:limit],
                    }
                return text_result(json_text(result))

            case "tmux_webui_relay":
                command = arguments.get("command", "")
                timeout = arguments.get("timeout", 30)
                wait = arguments.get("wait", False)

                dispatch = await to_thread(client.relay_dispatch, command, timeout)

                if wait and dispatch.get("signal_file"):
                    signal_file = dispatch["signal_file"]
                    import time

                    deadline = time.time() + timeout
                    while time.time() < deadline:
                        await asyncio.sleep(2)
                        check = await to_thread(client.relay_check, signal_file)
                        if check.get("status") == "completed":
                            dispatch["final_status"] = "completed"
                            break
                    else:
                        dispatch["final_status"] = "timeout"

                return text_result(json_text(dispatch))

            case "tmux_webui_autocomplete":
                if arguments.get("refresh"):
                    await to_thread(client.refresh_autocomplete)
                query = arguments.get("query", "")
                type_filter = arguments.get("type")
                limit = arguments.get("limit", 20)
                result = await to_thread(client.autocomplete, query, type_filter)
                # Slice suggestions if present
                if isinstance(result, dict) and "suggestions" in result:
                    total_count = len(result["suggestions"])
                    result = {
                        "total_count": total_count,
                        "items": result["suggestions"][:limit],
                    }
                elif isinstance(result, list):
                    total_count = len(result)
                    result = {
                        "total_count": total_count,
                        "items": result[:limit],
                    }
                return text_result(json_text(result))

            case _:
                return text_result(f"Unknown tool: {name}")

    except TmuxWebuiError as e:
        return text_result(f"tmux-webui API error ({e.status_code}): {e.detail}")
    except Exception as e:
        return text_result(f"Error: {type(e).__name__}: {e}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

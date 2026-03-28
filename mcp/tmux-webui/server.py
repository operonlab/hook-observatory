"""tmux-webui MCP Server -- tmux session management tools for Claude Code.

3 tools: tmux_webui_sessions, tmux_webui_relay, tmux_webui_autocomplete.

Usage (via .mcp.json):
    uv run --no-project --with 'mcp>=1.0' --with httpx python3 mcp/tmux-webui/server.py
"""

import asyncio
import json
from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from sdk_client.tmux_webui import TmuxWebuiClient
from sdk_client.mcp_helpers import mcp_error_handler

mcp = FastMCP("tmux-webui")
client = TmuxWebuiClient()


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@mcp.tool()
@mcp_error_handler("TmuxWebUI")
async def tmux_webui_sessions(session: str = "", limit: int = 20) -> str:
    """List tmux sessions with their windows and panes. Provides a complete view of the tmux environment."""
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
    return json_text(result)


@mcp.tool()
@mcp_error_handler("TmuxWebUI")
async def tmux_webui_relay(command: str, timeout: int = 30, wait: bool = False) -> str:
    """Dispatch a command to a tmux relay pane. Optionally poll for completion. Returns pane ID and signal file path."""
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

    return json_text(dispatch)


@mcp.tool()
@mcp_error_handler("TmuxWebUI")
async def tmux_webui_autocomplete(
    query: str, type: str = "", refresh: bool = False, limit: int = 20
) -> str:
    """Get autocomplete suggestions for tmux commands, sessions, or paths."""
    if refresh:
        await to_thread(client.refresh_autocomplete)
    type_filter = type or None
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
    return json_text(result)


if __name__ == "__main__":
    mcp.run()

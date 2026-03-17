#!/usr/bin/env python3
"""Hook Observatory MCP Server — Thin wrapper over HookObservatoryClient SDK.

3 tools: hook_obs_stats, hook_obs_events, hook_obs_tools.
All logic lives in workshop.clients.hook_observatory (SDK layer).

Usage:
    python3 mcp/hook-observatory/server.py

Configure in ~/.claude.json:
    "hook-observatory": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/hook-observatory/server.py"],
        "env": {}
    }
"""

import json
from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients.hook_observatory import HookObservatoryClient
from workshop.mcp_helpers import mcp_error_handler

mcp = FastMCP("hook-observatory")
client = HookObservatoryClient()


# ======================== Result Formatting ========================


def _format_stats(summary: dict, by_event: list | None = None) -> str:
    parts = [
        f"**Total events**: {summary.get('total', 0)}",
        f"**Today**: {summary.get('today', 0)}",
        f"**Unique sessions**: {summary.get('unique_sessions', 0)}",
    ]
    if by_event:
        parts.append("\n### By Event Type")
        for e in by_event[:15]:
            parts.append(
                f"- {e.get('event_type', '?')}: {e.get('count', 0)} (today: {e.get('today', 0)})"
            )
    return "\n".join(parts)


def _format_events(result: dict) -> str:
    items = result.get("items", [])
    total = result.get("total", 0)
    parts = [f"**Showing {len(items)} of {total} events**\n"]

    for evt in items:
        ts = str(evt.get("created_at", ""))[:19]
        payload_str = json.dumps(evt.get("payload", {}), ensure_ascii=False)
        if len(payload_str) > 200:
            payload_str = payload_str[:200] + "..."
        parts.append(
            f"- `{ts}` **{evt.get('event_type', '?')}** "
            f"tool={evt.get('tool_name', '-')} "
            f"session={str(evt.get('session_id', '-'))[:12]}"
        )

    return "\n".join(parts)


def _format_tools(tools: list) -> str:
    parts = ["### Tool Usage Ranking\n"]
    for i, t in enumerate(tools, 1):
        parts.append(f"{i}. **{t.get('tool_name', '?')}**: {t.get('count', 0)}")
    return "\n".join(parts)


# ======================== Tool Definitions ========================


@mcp.tool()
@mcp_error_handler("HookObservatory")
async def hook_obs_stats(include_by_event: bool = True) -> str:
    """Get Hook Observatory summary stats: total events, today count, unique sessions, and event type breakdown. Use this to understand Claude Code hook activity patterns."""
    summary = await to_thread(client.summary)
    by_event = None
    if include_by_event:
        by_event = await to_thread(client.stats_by_event)
    return _format_stats(summary, by_event)


@mcp.tool()
@mcp_error_handler("HookObservatory")
async def hook_obs_events(
    event_type: str | None = None,
    session_id: str | None = None,
    tool_name: str | None = None,
    limit: int = 20,
) -> str:
    """Query hook events with filters. Returns paginated event list with event_type, tool_name, session_id, payload, timestamp."""
    result = await to_thread(
        client.list_events,
        event_type=event_type,
        session_id=session_id,
        tool_name=tool_name,
        limit=limit,
    )
    return _format_events(result)


@mcp.tool()
@mcp_error_handler("HookObservatory")
async def hook_obs_tools(limit: int = 20) -> str:
    """Get tool usage ranking — which Claude Code tools are used most frequently. Useful for understanding workflow patterns."""
    tools = await to_thread(
        client.stats_by_tool,
        limit=limit,
    )
    return _format_tools(tools)


if __name__ == "__main__":
    mcp.run()

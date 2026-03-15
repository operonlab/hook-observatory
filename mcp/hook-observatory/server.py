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

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients.hook_observatory import HookObservatoryClient, HookObservatoryError

server = Server("hook-observatory")
client = HookObservatoryClient()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="hook_obs_stats",
            description=(
                "Get Hook Observatory summary stats: total events, today count, "
                "unique sessions, and event type breakdown. "
                "Use this to understand Claude Code hook activity patterns."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "include_by_event": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include per-event-type breakdown",
                    },
                },
            },
        ),
        Tool(
            name="hook_obs_events",
            description=(
                "Query hook events with filters. Returns paginated event list "
                "with event_type, tool_name, session_id, payload, timestamp."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "description": "Filter by event type (e.g. PostToolUse, PreToolUse)",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Filter by session ID",
                    },
                    "tool_name": {
                        "type": "string",
                        "description": "Filter by tool name (e.g. Bash, Read, Write)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "maximum": 100,
                        "description": "Max events to return",
                    },
                },
            },
        ),
        Tool(
            name="hook_obs_tools",
            description=(
                "Get tool usage ranking — which Claude Code tools are used most frequently. "
                "Useful for understanding workflow patterns."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "maximum": 100,
                        "description": "Max tools to return",
                    },
                },
            },
        ),
    ]


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


# ======================== Tool Handler ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "hook_obs_stats":
            summary = await to_thread(client.summary)
            by_event = None
            if arguments.get("include_by_event", True):
                by_event = await to_thread(client.stats_by_event)
            return text_result(_format_stats(summary, by_event))

        elif name == "hook_obs_events":
            result = await to_thread(
                client.list_events,
                event_type=arguments.get("event_type"),
                session_id=arguments.get("session_id"),
                tool_name=arguments.get("tool_name"),
                limit=arguments.get("limit", 20),
            )
            return text_result(_format_events(result))

        elif name == "hook_obs_tools":
            tools = await to_thread(
                client.stats_by_tool,
                limit=arguments.get("limit", 20),
            )
            return text_result(_format_tools(tools))

        return text_result(f"Unknown tool: {name}")

    except HookObservatoryError as e:
        return text_result(f"Hook Observatory error: {e}")
    except Exception as e:
        return text_result(f"Unexpected error: {type(e).__name__}: {e}")


# ======================== Main ========================


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

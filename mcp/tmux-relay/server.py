#!/usr/bin/env python3
"""tmux-relay MCP Server — Thin wrapper over TmuxRelayClient SDK.

5 tools: relay_run, relay_dispatch, relay_list, relay_check, relay_result.
All logic lives in workshop.clients.tmux_relay (SDK layer).

Usage:
    python3 mcp/tmux-relay/server.py

Configure in ~/.claude.json:
    "tmux-relay": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/tmux-relay/server.py"],
        "env": {}
    }
"""

import asyncio
from asyncio import to_thread

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients.tmux_relay import TmuxRelayClient, TmuxRelayError

server = Server("tmux-relay")
client = TmuxRelayClient()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="relay_run",
            description=(
                "Blocking relay: acquire pane → send command → wait for completion "
                "(event-driven via tmux wait-for, zero CPU) → return result. "
                "Use from a background Agent for true async. This is the PRIMARY tool."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command/prompt to send to the relay pane",
                    },
                    "timeout": {
                        "type": "integer",
                        "default": 600,
                        "description": "Max seconds to wait for completion",
                    },
                    "lines": {
                        "type": "integer",
                        "default": 200,
                        "description": "Max lines of output to return",
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="relay_dispatch",
            description=(
                "Low-level: fire-and-forget dispatch. Returns signal_file for manual "
                "polling via relay_check/relay_result. Prefer relay_run instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command/prompt to send to the relay pane",
                    },
                    "timeout": {
                        "type": "integer",
                        "default": 600,
                        "description": "Max seconds to wait for completion (background)",
                    },
                    "count": {
                        "type": "integer",
                        "default": 1,
                        "description": "Number of panes to dispatch to (for parallel tasks)",
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="relay_list",
            description="List all relay panes with their idle/busy status (cache-backed, ~0.5ms).",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="relay_check",
            description="Low-level: check if a dispatched command has completed (cache-backed, ~0.1ms).",
            inputSchema={
                "type": "object",
                "properties": {
                    "signal_file": {
                        "type": "string",
                        "description": "Path to the .done signal file returned by relay_dispatch",
                    },
                },
                "required": ["signal_file"],
            },
        ),
        Tool(
            name="relay_result",
            description="Low-level: read the output of a completed relay command.",
            inputSchema={
                "type": "object",
                "properties": {
                    "signal_file": {
                        "type": "string",
                        "description": "Path to the .done signal file",
                    },
                    "lines": {
                        "type": "integer",
                        "default": 200,
                        "description": "Max lines of output to return",
                    },
                },
                "required": ["signal_file"],
            },
        ),
    ]


# ======================== Result Formatting ========================


def _format_relay_result(result) -> str:
    parts = [f"**Pane**: {result.pane}"]
    if result.status:
        parts.append(f"**Status**: {result.status}")
    if result.elapsed:
        parts.append(f"**Elapsed**: {result.elapsed}")
    if result.result_file:
        parts.append(f"**Result file**: {result.result_file}")
    if result.output:
        total_lines = result.output.count("\n") + 1
        parts.append(f"\n## Output ({total_lines} lines)\n\n{result.output}")
    return "\n".join(parts)


def _format_dispatch(dispatched: list[dict]) -> str:
    parts = [f"**Dispatched {len(dispatched)} task(s)**\n"]
    for d in dispatched:
        parts.append(f"- Pane: {d['pane']}, Signal: {d['signal_file']}, PID: {d['pid']}")
    return "\n".join(parts)


def _format_panes(panes) -> str:
    if not panes:
        return "No relay panes found."
    parts = ["### Relay Panes\n"]
    for p in panes:
        indicator = "🟢" if p.status == "idle" else "🔴"
        parts.append(f"- {indicator} **{p.pane_ref}** — {p.status} ({p.pane_id})")
    return "\n".join(parts)


# ======================== Tool Handler ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "relay_run":
            result = await to_thread(
                client.run,
                command=arguments["command"],
                timeout=arguments.get("timeout", 600),
                max_lines=arguments.get("lines", 200),
            )
            return text_result(_format_relay_result(result))

        elif name == "relay_dispatch":
            dispatched = await to_thread(
                client.dispatch,
                command=arguments["command"],
                timeout=arguments.get("timeout", 600),
                count=arguments.get("count", 1),
            )
            return text_result(_format_dispatch(dispatched))

        elif name == "relay_list":
            panes = await to_thread(client.list_panes)
            return text_result(_format_panes(panes))

        elif name == "relay_check":
            result = await to_thread(
                client.check,
                signal_file=arguments["signal_file"],
            )
            status = result["status"].upper()
            meta = result.get("meta", "")
            return text_result(f"**Status**: {status}\nSignal: {result['signal_file']}\n{meta}")

        elif name == "relay_result":
            result = await to_thread(
                client.result,
                signal_file=arguments["signal_file"],
                max_lines=arguments.get("lines", 200),
            )
            return text_result(_format_relay_result(result))

        return text_result(f"Unknown tool: {name}")

    except TmuxRelayError as e:
        return text_result(f"tmux-relay error: {e}")


# ======================== Main ========================


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

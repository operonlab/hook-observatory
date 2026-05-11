#!/usr/bin/env python3
"""Session Channel MCP Server — cross-session messaging via Redis Streams.

Usage:
    python3 mcp/session-channel/server.py

Configure in mcpproxy:
    "session-channel": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/session-channel/server.py"]
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP

from sdk_client.mcp_helpers import mcp_error_handler
from sdk_client.session_channel import SessionChannelClient

mcp = FastMCP("session-channel")
client = SessionChannelClient()


@mcp.tool()
@mcp_error_handler("SessionChannel")
async def channel_send(topic: str, text: str, tag: str = "", priority: str = "normal") -> str:
    """Send a message to a session-channel topic."""
    result = await to_thread(
        client.send_message, topic, text, tag=tag or None, priority=priority
    )
    return f"Sent to [{result.get('topic')}] id={result.get('id')}"


@mcp.tool()
@mcp_error_handler("SessionChannel")
async def channel_read(topic: str, count: int = 20) -> str:
    """Read recent messages from a topic."""
    msgs = await to_thread(client.read_messages, topic, count=count)
    if not msgs:
        return f"No messages in topic '{topic}'"
    lines = []
    for m in msgs:
        tag = f" #{m['tag']}" if m.get("tag") else ""
        lines.append(f"{m.get('sender', '?')}: {m.get('text', '')}{tag}")
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("SessionChannel")
async def channel_topics() -> str:
    """List active topics with message counts."""
    topics = await to_thread(client.list_topics)
    if not topics:
        return "(no active topics)"
    return "\n".join(f"{t['topic']:>20}  {t['count']} msgs" for t in topics)


if __name__ == "__main__":
    mcp.run()

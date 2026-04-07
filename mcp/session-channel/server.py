#!/usr/bin/env python3
"""Session Channel MCP Server — cross-session messaging + task board.

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

from sdk_client.mcp_helpers import json_text, mcp_error_handler
from sdk_client.session_channel import SessionChannelClient

mcp = FastMCP("session-channel")
client = SessionChannelClient()


@mcp.tool()
@mcp_error_handler("SessionChannel")
async def channel_send(topic: str, text: str, tag: str = "", priority: str = "normal") -> str:
    """Send a message to a session-channel topic."""
    result = await to_thread(client.send, topic, text, tag=tag, priority=priority)
    return f"Sent to [{result.get('topic')}] id={result.get('id')}"


@mcp.tool()
@mcp_error_handler("SessionChannel")
async def channel_read(topic: str, count: int = 20) -> str:
    """Read recent messages from a topic."""
    msgs = await to_thread(client.read, topic, count=count)
    if not msgs:
        return f"No messages in topic '{topic}'"
    lines = []
    for m in msgs:
        tag = f" #{m['tag']}" if m.get("tag") else ""
        lines.append(f"{m.get('sender', '?')}: {m.get('text', '')}{tag}")
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("SessionChannel")
async def board_show(board_id: str) -> str:
    """Show task board state — tasks, claims, and completion status."""
    result = await to_thread(client.board_show, board_id)
    return json_text(result)


@mcp.tool()
@mcp_error_handler("SessionChannel")
async def board_publish(board_id: str, task_ids: str, task_descs: str = "") -> str:
    """Publish a task board. task_ids: comma-separated IDs. task_descs: comma-separated descriptions (optional)."""
    ids = [t.strip() for t in task_ids.split(",") if t.strip()]
    descs = [d.strip() for d in task_descs.split(",") if d.strip()] if task_descs else ids
    tasks = [{"id": tid, "desc": descs[i] if i < len(descs) else tid} for i, tid in enumerate(ids)]
    await to_thread(client.board_publish, board_id, tasks)
    return f"Board '{board_id}' published with {len(tasks)} tasks"


@mcp.tool()
@mcp_error_handler("SessionChannel")
async def board_claim(board_id: str, task_id: str) -> str:
    """Atomically claim a task on the board (Lua CAS exactly-once)."""
    result = await to_thread(client.board_claim, board_id, task_id)
    if result.get("ok"):
        return f"Claimed '{task_id}'"
    holder = result.get("holder", {})
    return f"Cannot claim '{task_id}': {result.get('reason')} (held by {holder.get('pane', '?')})"


@mcp.tool()
@mcp_error_handler("SessionChannel")
async def board_complete(board_id: str, task_id: str, result: str = "done") -> str:
    """Mark a task as completed on the board."""
    await to_thread(client.board_complete, board_id, task_id, result)
    return f"Completed '{task_id}'"


@mcp.tool()
@mcp_error_handler("SessionChannel")
async def board_drop(board_id: str, task_id: str) -> str:
    """Release a claimed task back to open status (only the claimer can drop)."""
    r = await to_thread(client.board_drop, board_id, task_id)
    if r.get("ok"):
        return f"Dropped '{task_id}'"
    return f"Cannot drop '{task_id}': {r.get('reason')}"


if __name__ == "__main__":
    mcp.run()

#!/usr/bin/env python3
"""fleet MCP Server — Thin wrapper over FleetClient SDK.

6 tools: fleet_nodes, fleet_dispatch, fleet_status,
         fleet_result, fleet_tasks, fleet_cancel.

All logic lives in workshop.clients.fleet (SDK layer).

Usage:
    python3 mcp/fleet/server.py

Configure in ~/.mcpproxy/mcp_config.json:
    "fleet": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/fleet/server.py"],
        "env": {}
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients.fleet import FleetClient
from workshop.mcp_helpers import mcp_error_handler

mcp = FastMCP("fleet")
client = FleetClient()


# ======================== Result Formatting ========================


def _format_nodes(nodes: list[dict]) -> str:
    if not nodes:
        return "No nodes registered."
    lines = [
        "| Node | Platform | Healthy | Capabilities | Active Tasks |",
        "|------|----------|---------|--------------|--------------|",
    ]
    for n in nodes:
        healthy = "✅" if n.get("healthy") else "❌"
        caps = ", ".join(n.get("capabilities", []))
        if n.get("gpu"):
            caps += f" | GPU: {n['gpu'].get('model', '?')}"
        lines.append(
            f"| {n.get('name', '?')} | {n.get('platform', '?')} | {healthy} "
            f"| {caps} | {n.get('active_tasks', 0)} |"
        )
    return "\n".join(lines)


def _format_task(task: dict) -> str:
    from datetime import datetime

    def _ts(epoch):
        if not epoch:
            return "-"
        return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")

    parts = [
        f"**Task**: `{task.get('id', '?')[:8]}`",
        f"**Command**: {task.get('command', '')[:80]}",
        f"**Node**: {task.get('node', '?')}",
        f"**Mode**: {task.get('mode', '?')}",
        f"**Status**: {task.get('status', '?')}",
        f"**Created**: {_ts(task.get('created_at'))}",
        f"**Started**: {_ts(task.get('started_at'))}",
        f"**Completed**: {_ts(task.get('completed_at'))}",
    ]
    if task.get("branch"):
        parts.append(f"**Branch**: {task['branch']}")
    if task.get("error"):
        parts.append(f"**Error**: {task['error']}")
    return "\n".join(parts)


def _format_tasks(tasks: list[dict]) -> str:
    if not tasks:
        return "No tasks found."
    lines = [
        "| ID | Status | Node | Mode | Created | Command |",
        "|----|--------|------|------|---------|---------|",
    ]
    from datetime import datetime

    for t in tasks:
        ts = "-"
        if t.get("created_at"):
            ts = datetime.fromtimestamp(t["created_at"]).strftime("%H:%M:%S")
        lines.append(
            f"| `{t['id'][:8]}` | {t.get('status', '?')} | {t.get('node', '?')} "
            f"| {t.get('mode', '?')} | {ts} | {t.get('command', '')[:40]} |"
        )
    return "\n".join(lines)


# ======================== Tool Handlers ========================


@mcp.tool()
@mcp_error_handler("Fleet")
async def fleet_nodes() -> str:
    """List all Fleet nodes with their capabilities, GPU info, health status, and active task count."""
    nodes = await to_thread(client.list_nodes)
    return _format_nodes(nodes)


@mcp.tool()
@mcp_error_handler("Fleet")
async def fleet_dispatch(
    command: str,
    mode: str = "code",
    node: str = "",
    timeout: int = 600,
) -> str:
    """Dispatch a task to a Fleet node for remote execution.

    Args:
        command: Task command or prompt string to execute remotely.
        mode: Execution mode — "code" (Claude Code agent) or "gpu" (GPU workload).
        node: Target node name. Leave empty for auto-selection.
        timeout: Task timeout in seconds (default: 600).
    """
    task = await to_thread(
        client.dispatch,
        command=command,
        mode=mode,
        node=node or None,
        timeout=timeout,
    )
    return _format_task(task)


@mcp.tool()
@mcp_error_handler("Fleet")
async def fleet_status(task_id: str) -> str:
    """Check the status and metadata of a Fleet task.

    Args:
        task_id: Task ID (short prefix or full UUID).
    """
    task = await to_thread(client.task_status, task_id)
    return _format_task(task)


@mcp.tool()
@mcp_error_handler("Fleet")
async def fleet_result(task_id: str, lines: int = 200) -> str:
    """Get the output (stdout/stderr) of a completed Fleet task.

    Args:
        task_id: Task ID (short prefix or full UUID).
        lines: Maximum number of output lines to return (default: 200).
    """
    result = await to_thread(client.task_output, task_id, lines)
    status = result.get("status", "?")
    output = result.get("output", "(no output)")
    return f"**Status**: {status}\n\n```\n{output}\n```"


@mcp.tool()
@mcp_error_handler("Fleet")
async def fleet_tasks(
    status: str = "",
    node: str = "",
) -> str:
    """List Fleet tasks with optional filters.

    Args:
        status: Filter by status (running, completed, failed, pending, cancelled).
        node: Filter by node name.
    """
    tasks = await to_thread(
        client.list_tasks,
        status=status or None,
        node=node or None,
    )
    return _format_tasks(tasks)


@mcp.tool()
@mcp_error_handler("Fleet")
async def fleet_cancel(task_id: str) -> str:
    """Cancel a running or pending Fleet task.

    Args:
        task_id: Task ID (short prefix or full UUID).
    """
    result = await to_thread(client.cancel_task, task_id)
    tid = result.get("id", task_id)[:8]
    status = result.get("status", "cancelled")
    return f"Task `{tid}` → **{status}**"


if __name__ == "__main__":
    mcp.run()

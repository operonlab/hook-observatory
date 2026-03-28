#!/usr/bin/env python3
"""Nodeflow MCP Server — thin wrapper over NodeflowClient SDK.

9 tools: nodeflow_flows, nodeflow_flow_detail, nodeflow_create_flow,
         nodeflow_trigger_flow, nodeflow_nodes, nodeflow_create_node,
         nodeflow_edges, nodeflow_runs, nodeflow_actions.

Usage:
    python3 mcp/nodeflow/server.py

Configure in ~/.claude.json:
    "nodeflow": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/nodeflow/server.py"],
        "env": {}
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from sdk_client.nodeflow import NodeflowClient
from sdk_client.mcp_helpers import mcp_error_handler

mcp = FastMCP("nodeflow")
client = NodeflowClient()


def _format_flows(result: dict) -> str:
    items = result.get("items", [])
    total = result.get("total", 0)
    if not items:
        return "No flows found."
    lines = [f"**Flows** ({len(items)} of {total})\n"]
    for f in items:
        status = f.get("status", "?")
        trigger = f.get("trigger_type", "?")
        lines.append(f"- **{f.get('name', '?')[:50]}** [{status}] trigger={trigger}")
        lines.append(f"  id: {f.get('id', '?')[:12]}")
    return "\n".join(lines)


def _format_flow_detail(f: dict) -> str:
    lines = [
        f"**{f.get('name', '?')}**",
        f"Status: {f.get('status', '?')} | Trigger: {f.get('trigger_type', '?')}",
    ]
    desc = f.get("description", "")
    if desc:
        lines.append(f"Description: {desc[:200]}")
    nodes = f.get("nodes", [])
    edges = f.get("edges", [])
    lines.append(f"\n**Nodes** ({len(nodes)}):")
    for n in nodes:
        lines.append(
            f"- {n.get('label', '?')} ({n.get('node_type', '?')}) id={n.get('id', '?')[:12]}"
        )
    lines.append(f"\n**Edges** ({len(edges)}):")
    for e in edges:
        src = e.get("source_node_id", "?")[:12]
        tgt = e.get("target_node_id", "?")[:12]
        lines.append(f"- {src} --> {tgt}")
    return "\n".join(lines)


def _format_nodes(result) -> str:
    items = result if isinstance(result, list) else result.get("items", [])
    if not items:
        return "No nodes found."
    lines = [f"**Nodes** ({len(items)})\n"]
    for n in items:
        lines.append(
            f"- **{n.get('label', '?')}** ({n.get('node_type', '?')}) "
            f"pos=({n.get('position_x', 0)}, {n.get('position_y', 0)}) "
            f"id={n.get('id', '?')[:12]}"
        )
    return "\n".join(lines)


def _format_edges(result) -> str:
    items = result if isinstance(result, list) else result.get("items", [])
    if not items:
        return "No edges found."
    lines = [f"**Edges** ({len(items)})\n"]
    for e in items:
        src = e.get("source_node_id", "?")[:12]
        tgt = e.get("target_node_id", "?")[:12]
        port = e.get("source_port", "output")
        lines.append(f"- {src} --[{port}]--> {tgt}  id={e.get('id', '?')[:12]}")
    return "\n".join(lines)


def _format_runs(result: dict) -> str:
    items = result.get("items", [])
    total = result.get("total", 0)
    if not items:
        return "No runs found."
    lines = [f"**Runs** ({len(items)} of {total})\n"]
    for r in items:
        status = r.get("status", "?")
        started = str(r.get("started_at", ""))[:19]
        lines.append(f"- [{status}] started={started} id={r.get('id', '?')[:12]}")
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Nodeflow")
async def nodeflow_flows(page: int = 1, page_size: int = 20) -> str:
    """List workflow DAG flows with name, status, and trigger type. Supports pagination."""
    result = await to_thread(client.list_flows, page=page, page_size=page_size)
    return _format_flows(result)


@mcp.tool()
@mcp_error_handler("Nodeflow")
async def nodeflow_flow_detail(flow_id: str) -> str:
    """Get flow detail including nodes and edges."""
    result = await to_thread(client.get_flow, flow_id)
    return _format_flow_detail(result)


@mcp.tool()
@mcp_error_handler("Nodeflow")
async def nodeflow_create_flow(
    name: str,
    description: str = "",
    trigger_type: str = "manual",
    trigger_config: dict = None,
) -> str:
    """Create a new workflow DAG flow with name, description, and trigger type (manual/scheduled/event)."""
    data = {"name": name, "status": "draft"}
    if description:
        data["description"] = description
    data["trigger_type"] = trigger_type
    if trigger_config is not None:
        data["trigger_config"] = trigger_config
    result = await to_thread(client.create_flow, data)
    return f"Flow created: **{result.get('name', '?')}** (id: {result.get('id', '?')[:12]})"


@mcp.tool()
@mcp_error_handler("Nodeflow")
async def nodeflow_trigger_flow(flow_id: str, input_data: dict = None) -> str:
    """Manually trigger a flow execution."""
    input_data = input_data or {}
    result = await to_thread(client.trigger_flow, flow_id, input_data)
    run_id = result.get("id", result.get("flow_run_id", "?"))
    return f"Flow triggered. Run ID: {run_id}"


@mcp.tool()
@mcp_error_handler("Nodeflow")
async def nodeflow_nodes(flow_id: str, limit: int = 50) -> str:
    """List all nodes in a workflow flow with type, label, config, and position."""
    result = await to_thread(client.list_nodes, flow_id)
    items = result if isinstance(result, list) else result.get("items", [])
    total_count = len(items)
    items = items[:limit]
    return f"Showing {len(items)} of {total_count} nodes\n\n" + _format_nodes(items)


@mcp.tool()
@mcp_error_handler("Nodeflow")
async def nodeflow_create_node(
    flow_id: str,
    node_type: str,
    label: str,
    config: dict = None,
    position_x: float = 0,
    position_y: float = 0,
) -> str:
    """Create a workflow node in a DAG flow. Specify node_type, label, config, and position."""
    data = {
        "flow_id": flow_id,
        "node_type": node_type,
        "label": label,
        "config": config or {},
        "position_x": position_x,
        "position_y": position_y,
    }
    result = await to_thread(client.create_node, data)
    return f"Node created: **{result.get('label', '?')}** (id: {result.get('id', '?')[:12]})"


@mcp.tool()
@mcp_error_handler("Nodeflow")
async def nodeflow_edges(flow_id: str, limit: int = 50) -> str:
    """List all edges (connections between nodes) in a workflow flow with source and target node IDs."""
    result = await to_thread(client.list_edges, flow_id)
    items = result if isinstance(result, list) else result.get("items", [])
    total_count = len(items)
    items = items[:limit]
    return f"Showing {len(items)} of {total_count} edges\n\n" + _format_edges(items)


@mcp.tool()
@mcp_error_handler("Nodeflow")
async def nodeflow_runs(flow_id: str, page: int = 1, page_size: int = 20) -> str:
    """List execution runs for a flow."""
    result = await to_thread(
        client.list_runs,
        flow_id,
        page=page,
        page_size=page_size,
    )
    return _format_runs(result)


@mcp.tool()
@mcp_error_handler("Nodeflow")
async def nodeflow_actions() -> str:
    """List available action types for building flows."""
    result = await to_thread(client.list_actions)
    items = result if isinstance(result, list) else result.get("items", [])
    if not items:
        return "No actions available."
    lines = [f"**Available Actions** ({len(items)})\n"]
    for a in items:
        name_str = a.get("name", a.get("type", "?"))
        desc = a.get("description", "")[:60]
        lines.append(f"- **{name_str}**: {desc}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()

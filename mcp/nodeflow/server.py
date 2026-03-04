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

import asyncio
import json
from asyncio import to_thread

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.nodeflow import NodeflowClient

server = Server("nodeflow")
client = NodeflowClient()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="nodeflow_flows",
            description="List DAG flows with pagination.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="nodeflow_flow_detail",
            description="Get flow detail including nodes and edges.",
            inputSchema={
                "type": "object",
                "properties": {
                    "flow_id": {"type": "string", "description": "Flow ID"},
                },
                "required": ["flow_id"],
            },
        ),
        Tool(
            name="nodeflow_create_flow",
            description="Create a new DAG flow.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Flow name"},
                    "description": {"type": "string", "description": "Flow description"},
                    "trigger_type": {
                        "type": "string",
                        "enum": ["manual", "event", "schedule"],
                        "default": "manual",
                    },
                    "trigger_config": {"type": "object", "description": "Trigger configuration"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="nodeflow_trigger_flow",
            description="Manually trigger a flow execution.",
            inputSchema={
                "type": "object",
                "properties": {
                    "flow_id": {"type": "string", "description": "Flow ID"},
                    "input_data": {"type": "object", "description": "Input data for the flow"},
                },
                "required": ["flow_id"],
            },
        ),
        Tool(
            name="nodeflow_nodes",
            description="List nodes in a flow.",
            inputSchema={
                "type": "object",
                "properties": {
                    "flow_id": {"type": "string", "description": "Flow ID"},
                },
                "required": ["flow_id"],
            },
        ),
        Tool(
            name="nodeflow_create_node",
            description="Create a node in a flow.",
            inputSchema={
                "type": "object",
                "properties": {
                    "flow_id": {"type": "string", "description": "Flow ID"},
                    "node_type": {"type": "string", "description": "Node type (action type)"},
                    "label": {"type": "string", "description": "Node display label"},
                    "config": {"type": "object", "description": "Node configuration"},
                    "position_x": {"type": "number", "default": 0},
                    "position_y": {"type": "number", "default": 0},
                },
                "required": ["flow_id", "node_type", "label"],
            },
        ),
        Tool(
            name="nodeflow_edges",
            description="List edges in a flow.",
            inputSchema={
                "type": "object",
                "properties": {
                    "flow_id": {"type": "string", "description": "Flow ID"},
                },
                "required": ["flow_id"],
            },
        ),
        Tool(
            name="nodeflow_runs",
            description="List execution runs for a flow.",
            inputSchema={
                "type": "object",
                "properties": {
                    "flow_id": {"type": "string", "description": "Flow ID"},
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
                "required": ["flow_id"],
            },
        ),
        Tool(
            name="nodeflow_actions",
            description="List available action types for building flows.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


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


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        match name:
            case "nodeflow_flows":
                result = await to_thread(
                    client.list_flows,
                    page=arguments.get("page", 1),
                    page_size=arguments.get("page_size", 20),
                )
                return text_result(_format_flows(result))

            case "nodeflow_flow_detail":
                result = await to_thread(client.get_flow, arguments["flow_id"])
                return text_result(_format_flow_detail(result))

            case "nodeflow_create_flow":
                data = {"name": arguments["name"], "status": "draft"}
                if "description" in arguments:
                    data["description"] = arguments["description"]
                data["trigger_type"] = arguments.get("trigger_type", "manual")
                if "trigger_config" in arguments:
                    data["trigger_config"] = arguments["trigger_config"]
                result = await to_thread(client.create_flow, data)
                return text_result(
                    f"Flow created: **{result.get('name', '?')}** (id: {result.get('id', '?')[:12]})"
                )

            case "nodeflow_trigger_flow":
                input_data = arguments.get("input_data", {})
                result = await to_thread(client.trigger_flow, arguments["flow_id"], input_data)
                run_id = result.get("id", result.get("flow_run_id", "?"))
                return text_result(f"Flow triggered. Run ID: {run_id}")

            case "nodeflow_nodes":
                result = await to_thread(client.list_nodes, arguments["flow_id"])
                return text_result(_format_nodes(result))

            case "nodeflow_create_node":
                data = {
                    "flow_id": arguments["flow_id"],
                    "node_type": arguments["node_type"],
                    "label": arguments["label"],
                    "config": arguments.get("config", {}),
                    "position_x": arguments.get("position_x", 0),
                    "position_y": arguments.get("position_y", 0),
                }
                result = await to_thread(client.create_node, data)
                return text_result(
                    f"Node created: **{result.get('label', '?')}** (id: {result.get('id', '?')[:12]})"
                )

            case "nodeflow_edges":
                result = await to_thread(client.list_edges, arguments["flow_id"])
                return text_result(_format_edges(result))

            case "nodeflow_runs":
                result = await to_thread(
                    client.list_runs,
                    arguments["flow_id"],
                    page=arguments.get("page", 1),
                    page_size=arguments.get("page_size", 20),
                )
                return text_result(_format_runs(result))

            case "nodeflow_actions":
                result = await to_thread(client.list_actions)
                items = result if isinstance(result, list) else result.get("items", [])
                if not items:
                    return text_result("No actions available.")
                lines = [f"**Available Actions** ({len(items)})\n"]
                for a in items:
                    name_str = a.get("name", a.get("type", "?"))
                    desc = a.get("description", "")[:60]
                    lines.append(f"- **{name_str}**: {desc}")
                return text_result("\n".join(lines))

            case _:
                return text_result(f"Unknown tool: {name}")

    except (APIError, APIConnectionError) as e:
        return text_result(f"Nodeflow error: {e}")
    except Exception as e:
        return text_result(f"Error: {type(e).__name__}: {e}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

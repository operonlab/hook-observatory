#!/usr/bin/env python3
"""Intelflow MCP Server — thin wrapper over IntelflowClient SDK.

7 tools: intelflow_reports, intelflow_report_search, intelflow_topics,
         intelflow_topic_graph, intelflow_briefings, intelflow_briefing,
         intelflow_dashboard.

Usage:
    python3 mcp/intelflow/server.py

Configure in ~/.claude.json:
    "intelflow": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/intelflow/server.py"],
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
from workshop.clients.intelflow import IntelflowClient

server = Server("intelflow")
client = IntelflowClient()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="intelflow_reports",
            description="List intelligence reports with optional filters (tag, topic).",
            inputSchema={
                "type": "object",
                "properties": {
                    "tag": {"type": "string", "description": "Filter by tag"},
                    "topic_id": {"type": "string", "description": "Filter by topic ID"},
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="intelflow_report_search",
            description="Semantic search over intelligence reports.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="intelflow_report_create",
            description="Create a new intelligence report.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Report title"},
                    "query": {"type": "string", "description": "Original query"},
                    "content": {"type": "string", "description": "Report content (markdown)"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for categorization",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Source references",
                    },
                    "skill_name": {"type": "string", "description": "Skill that generated this"},
                },
                "required": ["title", "query", "content"],
            },
        ),
        Tool(
            name="intelflow_topics",
            description="List intelligence topics with report counts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_size": {
                        "type": "integer",
                        "default": 50,
                        "description": "Page size (max 100)",
                    },
                },
            },
        ),
        Tool(
            name="intelflow_topic_graph",
            description="Get topic relationship graph (nodes + edges).",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_nodes": {
                        "type": "integer",
                        "default": 50,
                        "description": "Maximum number of nodes to return",
                    },
                },
            },
        ),
        Tool(
            name="intelflow_briefings",
            description="List daily briefings with optional date range filter.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "date_to": {"type": "string", "description": "End date YYYY-MM-DD"},
                    "page_size": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="intelflow_dashboard",
            description="Get Intelflow dashboard summary (report counts, recent activity).",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_list_items": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum items per list field in dashboard",
                    },
                },
            },
        ),
    ]


def _format_reports(result: dict) -> str:
    items = result.get("items", [])
    total = result.get("total", 0)
    if not items:
        return "No reports found."
    lines = [f"**Reports** ({len(items)} of {total})\n"]
    for r in items:
        date = str(r.get("created_at", ""))[:10]
        tags = ", ".join(r.get("tags", [])[:3])
        lines.append(f"- [{date}] **{r.get('title', '?')[:60]}**")
        if tags:
            lines.append(f"  tags: {tags} | id: {r.get('id', '?')[:12]}")
    return "\n".join(lines)


def _format_search(results) -> str:
    items = results if isinstance(results, list) else results.get("items", [])
    if not items:
        return "No results found."
    lines = [f"**Search Results** ({len(items)})\n"]
    for r in items:
        score = r.get("score", r.get("similarity", 0))
        lines.append(
            f"- [{score:.3f}] **{r.get('title', '?')[:60]}** (id: {r.get('id', '?')[:12]})"
        )
    return "\n".join(lines)


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        match name:
            case "intelflow_reports":
                result = await to_thread(
                    client.list_reports,
                    page=arguments.get("page", 1),
                    page_size=arguments.get("page_size", 20),
                    tag=arguments.get("tag"),
                    topic_id=arguments.get("topic_id"),
                )
                return text_result(_format_reports(result))

            case "intelflow_report_search":
                result = await to_thread(
                    client.semantic_search,
                    query=arguments["query"],
                    limit=arguments.get("limit", 5),
                )
                return text_result(_format_search(result))

            case "intelflow_report_create":
                result = await to_thread(
                    client.create_report,
                    title=arguments["title"],
                    query=arguments["query"],
                    content=arguments["content"],
                    tags=arguments.get("tags"),
                    sources=arguments.get("sources"),
                    skill_name=arguments.get("skill_name"),
                )
                return text_result(
                    f"Report created: **{result.get('title', '?')}** (id: {result.get('id', '?')[:12]})"
                )

            case "intelflow_topics":
                page_size = min(arguments.get("page_size", 50), 100)
                result = await to_thread(
                    client.list_topics,
                    page_size=page_size,
                )
                items = result.get("items", []) if isinstance(result, dict) else result
                if not items:
                    return text_result("No topics found.")
                lines = [f"**Topics** ({len(items)})\n"]
                for t in items:
                    lines.append(f"- **{t.get('name', '?')}** ({t.get('report_count', 0)} reports)")
                return text_result("\n".join(lines))

            case "intelflow_topic_graph":
                result = await to_thread(client.get_topic_graph)
                max_nodes = arguments.get("max_nodes", 50)
                if isinstance(result, dict):
                    nodes = result.get("nodes", [])
                    total_nodes = len(nodes)
                    if total_nodes > max_nodes:
                        kept_ids = {n.get("id") for n in nodes[:max_nodes]}
                        edges = result.get("edges", [])
                        total_edges = len(edges)
                        filtered_edges = [
                            e
                            for e in edges
                            if e.get("source") in kept_ids and e.get("target") in kept_ids
                        ]
                        result = {
                            "total_nodes": total_nodes,
                            "total_edges": total_edges,
                            "nodes": nodes[:max_nodes],
                            "edges": filtered_edges,
                            "truncated": True,
                        }
                return text_result(json_text(result))

            case "intelflow_briefings":
                result = await to_thread(
                    client.list_briefings,
                    date_from=arguments.get("date_from"),
                    date_to=arguments.get("date_to"),
                    page_size=arguments.get("page_size", 20),
                )
                items = result.get("items", []) if isinstance(result, dict) else result
                if not items:
                    return text_result("No briefings found.")
                lines = [f"**Briefings** ({len(items)})\n"]
                for b in items:
                    date = str(b.get("briefing_date", b.get("created_at", "")))[:10]
                    lines.append(f"- [{date}] {b.get('domain', '?')}")
                return text_result("\n".join(lines))

            case "intelflow_dashboard":
                result = await to_thread(client.get_dashboard)
                max_list_items = arguments.get("max_list_items", 10)
                if isinstance(result, dict):
                    for key, val in result.items():
                        if isinstance(val, list) and len(val) > max_list_items:
                            result[key] = val[:max_list_items]
                            result[f"{key}_total"] = len(val)
                return text_result(json_text(result))

            case _:
                return text_result(f"Unknown tool: {name}")

    except (APIError, APIConnectionError) as e:
        return text_result(f"Intelflow error: {e}")
    except Exception as e:
        return text_result(f"Error: {type(e).__name__}: {e}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

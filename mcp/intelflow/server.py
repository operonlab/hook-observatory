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

import json
from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.intelflow import IntelflowClient

mcp = FastMCP("intelflow")
client = IntelflowClient()


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


@mcp.tool()
async def intelflow_reports(
    tag: str | None = None,
    topic_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List intelligence reports with optional filters (tag, topic)."""
    try:
        result = await to_thread(
            client.list_reports,
            page=page,
            page_size=page_size,
            tag=tag,
            topic_id=topic_id,
        )
        return _format_reports(result)
    except (APIError, APIConnectionError) as e:
        return f"Intelflow error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def intelflow_report_search(query: str, limit: int = 5) -> str:
    """Semantic search over intelligence reports."""
    try:
        result = await to_thread(
            client.semantic_search,
            query=query,
            limit=limit,
        )
        return _format_search(result)
    except (APIError, APIConnectionError) as e:
        return f"Intelflow error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def intelflow_report_create(
    title: str,
    query: str,
    content: str,
    tags: list = None,
    sources: list = None,
    skill_name: str | None = None,
) -> str:
    """Create a new intelligence report."""
    try:
        result = await to_thread(
            client.create_report,
            title=title,
            query=query,
            content=content,
            tags=tags,
            sources=sources,
            skill_name=skill_name,
        )
        return f"Report created: **{result.get('title', '?')}** (id: {result.get('id', '?')[:12]})"
    except (APIError, APIConnectionError) as e:
        return f"Intelflow error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def intelflow_topics(page_size: int = 50) -> str:
    """List intelligence topics with report counts."""
    try:
        page_size = min(page_size, 100)
        result = await to_thread(
            client.list_topics,
            page_size=page_size,
        )
        items = result.get("items", []) if isinstance(result, dict) else result
        if not items:
            return "No topics found."
        lines = [f"**Topics** ({len(items)})\n"]
        for t in items:
            lines.append(f"- **{t.get('name', '?')}** ({t.get('report_count', 0)} reports)")
        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"Intelflow error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def intelflow_topic_graph(max_nodes: int = 50) -> str:
    """Get topic relationship graph (nodes + edges)."""
    try:
        result = await to_thread(client.get_topic_graph)
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
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except (APIError, APIConnectionError) as e:
        return f"Intelflow error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def intelflow_briefings(
    date_from: str | None = None,
    date_to: str | None = None,
    page_size: int = 20,
) -> str:
    """List daily briefings with optional date range filter."""
    try:
        result = await to_thread(
            client.list_briefings,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
        )
        items = result.get("items", []) if isinstance(result, dict) else result
        if not items:
            return "No briefings found."
        lines = [f"**Briefings** ({len(items)})\n"]
        for b in items:
            date = str(b.get("briefing_date", b.get("created_at", "")))[:10]
            lines.append(f"- [{date}] {b.get('domain', '?')}")
        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"Intelflow error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def intelflow_dashboard(max_list_items: int = 10) -> str:
    """Get Intelflow dashboard summary (report counts, recent activity)."""
    try:
        result = await to_thread(client.get_dashboard)
        if isinstance(result, dict):
            for key, val in result.items():
                if isinstance(val, list) and len(val) > max_list_items:
                    result[key] = val[:max_list_items]
                    result[f"{key}_total"] = len(val)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except (APIError, APIConnectionError) as e:
        return f"Intelflow error: {e}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run()

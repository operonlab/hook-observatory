#!/usr/bin/env python3
"""Paper MCP Server — thin wrapper over PaperClient SDK.

7 tools: paper_articles, paper_article_search, paper_article_create,
         paper_article_detail, paper_digest, paper_annotate, paper_dashboard.

Usage:
    python3 mcp/paper/server.py

Configure in ~/.mcpproxy/mcp_config.json:
    "paper": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/paper/server.py"],
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
from workshop.clients.paper import PaperClient

server = Server("paper")
client = PaperClient()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="paper_articles",
            description="List academic paper articles with optional filters (category, tag, relevance, cannibalize candidates).",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Filter by arXiv category (e.g. cs.AI)"},
                    "tag": {"type": "string", "description": "Filter by tag"},
                    "relevance": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Filter by workshop relevance level",
                    },
                    "cannibalize_candidate": {
                        "type": "boolean",
                        "description": "If true, show only cannibalize candidates",
                    },
                    "page": {"type": "integer", "default": 1},
                    "page_size": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="paper_article_search",
            description="Semantic search over academic papers. Returns ranked results with similarity scores.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (natural language)"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="paper_article_create",
            description="Create a new paper article entry with metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Paper title"},
                    "abstract": {"type": "string", "description": "Paper abstract"},
                    "arxiv_id": {"type": "string", "description": "arXiv identifier (e.g. 2401.12345)"},
                    "doi": {"type": "string", "description": "DOI"},
                    "year": {"type": "integer", "description": "Publication year"},
                    "authors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Author name list",
                    },
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "arXiv categories (e.g. cs.AI, cs.CL)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for categorization",
                    },
                    "source_url": {"type": "string", "description": "Source URL"},
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="paper_article_detail",
            description="Get full details of a paper article including metadata, abstract, and linked digest.",
            inputSchema={
                "type": "object",
                "properties": {
                    "article_id": {"type": "string", "description": "Article ID (full UUID)"},
                },
                "required": ["article_id"],
            },
        ),
        Tool(
            name="paper_digest",
            description="Get or generate a structured LLM digest for a paper (one-liner, key findings, relevance, actionable insight).",
            inputSchema={
                "type": "object",
                "properties": {
                    "article_id": {"type": "string", "description": "Article ID (full UUID)"},
                    "generate": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, trigger digest generation (may take longer)",
                    },
                },
                "required": ["article_id"],
            },
        ),
        Tool(
            name="paper_annotate",
            description="Add an annotation (note, highlight, question, synthesis, action-taken) to a paper article.",
            inputSchema={
                "type": "object",
                "properties": {
                    "article_id": {"type": "string", "description": "Article ID (full UUID)"},
                    "note": {"type": "string", "description": "Annotation text"},
                    "annotation_type": {
                        "type": "string",
                        "enum": ["note", "highlight", "question", "synthesis", "action-taken"],
                        "default": "note",
                        "description": "Type of annotation",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for the annotation",
                    },
                },
                "required": ["article_id", "note"],
            },
        ),
        Tool(
            name="paper_dashboard",
            description="Get Paper module dashboard summary (article counts, relevance distribution, recent activity).",
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


def _format_articles(result: dict) -> str:
    items = result.get("items", [])
    total = result.get("total", 0)
    if not items:
        return "No articles found."
    lines = [f"**Articles** ({len(items)} of {total})\n"]
    for a in items:
        year = a.get("year", "?")
        cats = ", ".join((a.get("categories") or [])[:2])
        lines.append(f"- [{year}] **{a.get('title', '?')[:60]}**")
        if cats:
            lines.append(f"  categories: {cats} | id: {a.get('id', '?')}")
        else:
            lines.append(f"  id: {a.get('id', '?')}")
    return "\n".join(lines)


def _format_search(results) -> str:
    items = results if isinstance(results, list) else results.get("items", [])
    if not items:
        return "No results found."
    lines = [f"**Search Results** ({len(items)})\n"]
    for r in items:
        score = r.get("score", r.get("similarity", 0))
        lines.append(
            f"- [{score:.3f}] **{r.get('title', '?')[:60]}** (id: {r.get('id', '?')})"
        )
    return "\n".join(lines)


def _format_article_detail(a: dict) -> str:
    lines = [f"# {a.get('title', '?')}\n"]
    authors = a.get("authors") or []
    if authors:
        names = ", ".join(str(x) for x in authors)
        lines.append(f"**Authors**: {names}")
    lines.append(f"**Year**: {a.get('year', '?')}")
    arxiv = a.get("arxiv_id")
    if arxiv:
        lines.append(f"**arXiv**: {arxiv}")
    doi = a.get("doi")
    if doi:
        lines.append(f"**DOI**: {doi}")
    cats = a.get("categories") or []
    if cats:
        lines.append(f"**Categories**: {', '.join(cats)}")
    tags = a.get("tags") or []
    if tags:
        lines.append(f"**Tags**: {', '.join(tags)}")
    lines.append(f"\n**Abstract**:\n{a.get('abstract', '')[:2000]}")
    lines.append(f"\nid: {a.get('id', '?')}")
    return "\n".join(lines)


def _format_digest(d: dict) -> str:
    lines = [f"**Digest**: {d.get('one_liner', '-')}\n"]
    lines.append(f"- Relevance: {d.get('workshop_relevance', '?')}")
    lines.append(f"- Confidence: {d.get('confidence', '?')}")
    lines.append(f"- Model: {d.get('model_used', '?')}")
    findings = d.get("key_findings", [])
    if findings:
        lines.append("\n**Key Findings**:")
        for i, f in enumerate(findings, 1):
            lines.append(f"  {i}. {f}")
    insight = d.get("actionable_insight")
    if insight:
        lines.append(f"\n**Actionable Insight**: {insight}")
    modules = d.get("applicable_modules", [])
    if modules:
        lines.append(f"**Applicable Modules**: {', '.join(modules)}")
    return "\n".join(lines)


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        match name:
            case "paper_articles":
                result = await to_thread(
                    client.list_articles,
                    page=arguments.get("page", 1),
                    page_size=arguments.get("page_size", 20),
                    category=arguments.get("category"),
                    tag=arguments.get("tag"),
                    relevance=arguments.get("relevance"),
                    cannibalize_candidate=arguments.get("cannibalize_candidate"),
                )
                return text_result(_format_articles(result))

            case "paper_article_search":
                result = await to_thread(
                    client.search,
                    query=arguments["query"],
                    limit=arguments.get("limit", 5),
                )
                return text_result(_format_search(result))

            case "paper_article_create":
                result = await to_thread(
                    client.create_article,
                    title=arguments["title"],
                    abstract=arguments.get("abstract"),
                    arxiv_id=arguments.get("arxiv_id"),
                    doi=arguments.get("doi"),
                    year=arguments.get("year"),
                    authors=arguments.get("authors"),
                    categories=arguments.get("categories"),
                    tags=arguments.get("tags"),
                    source_url=arguments.get("source_url"),
                )
                return text_result(
                    f"Article created: **{result.get('title', '?')}** (id: {result.get('id', '?')})"
                )

            case "paper_article_detail":
                result = await to_thread(
                    client.get_article,
                    article_id=arguments["article_id"],
                )
                return text_result(_format_article_detail(result))

            case "paper_digest":
                article_id = arguments["article_id"]
                if arguments.get("generate"):
                    result = await to_thread(
                        client.trigger_digest,
                        article_id=article_id,
                    )
                else:
                    result = await to_thread(
                        client.get_digest,
                        article_id=article_id,
                    )
                return text_result(_format_digest(result))

            case "paper_annotate":
                result = await to_thread(
                    client.create_annotation,
                    article_id=arguments["article_id"],
                    note=arguments["note"],
                    annotation_type=arguments.get("annotation_type", "note"),
                    tags=arguments.get("tags"),
                )
                return text_result(
                    f"Annotation added (type: {result.get('annotation_type', 'note')}, "
                    f"id: {result.get('id', '?')})"
                )

            case "paper_dashboard":
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
        return text_result(f"Paper error: {e}")
    except Exception as e:
        return text_result(f"Error: {type(e).__name__}: {e}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

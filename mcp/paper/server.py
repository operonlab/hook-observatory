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

from asyncio import to_thread
from typing import Optional

from mcp.server.fastmcp import FastMCP
from workshop.clients.paper import PaperClient
from workshop.mcp_helpers import build_body, json_text, mcp_error_handler

mcp = FastMCP("paper")
client = PaperClient()


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


@mcp.tool()
@mcp_error_handler("Paper")
async def paper_articles(
    category: Optional[str] = None,
    tag: Optional[str] = None,
    relevance: Optional[str] = None,
    cannibalize_candidate: Optional[bool] = None,
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List academic paper articles with optional filters (category, tag, relevance, cannibalize candidates)."""
    result = await to_thread(
        client.list_articles,
        page=page,
        page_size=page_size,
        category=category,
        tag=tag,
        relevance=relevance,
        cannibalize_candidate=cannibalize_candidate,
    )
    return _format_articles(result)


@mcp.tool()
@mcp_error_handler("Paper")
async def paper_article_search(query: str, limit: int = 5) -> str:
    """Semantic search over academic papers. Returns ranked results with similarity scores."""
    result = await to_thread(
        client.search,
        query=query,
        limit=limit,
    )
    return _format_search(result)


@mcp.tool()
@mcp_error_handler("Paper")
async def paper_article_create(
    title: str,
    abstract: Optional[str] = None,
    arxiv_id: Optional[str] = None,
    doi: Optional[str] = None,
    year: Optional[int] = None,
    authors: Optional[list[str]] = None,
    categories: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    source_url: Optional[str] = None,
) -> str:
    """Create a new paper article entry with metadata."""
    body = build_body(
        {"title": title},
        abstract=abstract,
        arxiv_id=arxiv_id,
        doi=doi,
        year=year,
        authors=authors,
        categories=categories,
        tags=tags,
        source_url=source_url,
    )
    result = await to_thread(client.create_article, **body)
    return f"Article created: **{result.get('title', '?')}** (id: {result.get('id', '?')})"


@mcp.tool()
@mcp_error_handler("Paper")
async def paper_article_detail(article_id: str) -> str:
    """Get full details of a paper article including metadata, abstract, and linked digest."""
    result = await to_thread(
        client.get_article,
        article_id=article_id,
    )
    return _format_article_detail(result)


@mcp.tool()
@mcp_error_handler("Paper")
async def paper_digest(article_id: str, generate: bool = False) -> str:
    """Get or generate a structured LLM digest for a paper (one-liner, key findings, relevance, actionable insight)."""
    if generate:
        result = await to_thread(
            client.trigger_digest,
            article_id=article_id,
        )
    else:
        result = await to_thread(
            client.get_digest,
            article_id=article_id,
        )
    return _format_digest(result)


@mcp.tool()
@mcp_error_handler("Paper")
async def paper_annotate(
    article_id: str,
    note: str,
    annotation_type: str = "note",
    tags: Optional[list[str]] = None,
) -> str:
    """Add an annotation (note, highlight, question, synthesis, action-taken) to a paper article."""
    result = await to_thread(
        client.create_annotation,
        article_id=article_id,
        note=note,
        annotation_type=annotation_type,
        tags=tags,
    )
    return (
        f"Annotation added (type: {result.get('annotation_type', 'note')}, "
        f"id: {result.get('id', '?')})"
    )


@mcp.tool()
@mcp_error_handler("Paper")
async def paper_dashboard(max_list_items: int = 10) -> str:
    """Get Paper module dashboard summary (article counts, relevance distribution, recent activity)."""
    result = await to_thread(client.get_dashboard)
    if isinstance(result, dict):
        for key, val in result.items():
            if isinstance(val, list) and len(val) > max_list_items:
                result[key] = val[:max_list_items]
                result[f"{key}_total"] = len(val)
    return json_text(result)


if __name__ == "__main__":
    mcp.run()

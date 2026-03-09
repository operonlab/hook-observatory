#!/usr/bin/env python3
"""Crawl4AI MCP Server — web crawling, chunking, URL filtering, and markdown generation.

8 tools: crawl4ai_crawl, crawl4ai_crawl_batch, crawl4ai_chunk,
         crawl4ai_filter_urls, crawl4ai_score_urls, crawl4ai_html_to_markdown,
         crawl4ai_analyze_url, crawl4ai_status.

Usage:
    python3 mcp/crawl4ai/server.py

Configure in ~/.claude.json:
    "crawl4ai": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/crawl4ai/server.py"],
        "env": {}
    }
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Resolve Workshop shared modules (core/src)
_CORE_SRC = Path(__file__).resolve().parents[2] / "core" / "src"
if str(_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(_CORE_SRC))

from shared.chunking import (  # noqa: E402
    FixedLengthChunking,
    RegexChunking,
    SentenceChunking,
    SlidingWindowChunking,
)
from shared.markdown_gen import DefaultMarkdownGenerator  # noqa: E402
from shared.url_filter import (  # noqa: E402
    DomainFilter,
    DuplicateFilter,
    FilterChain,
    PathPatternFilter,
)
from shared.url_scorer import (  # noqa: E402
    CompositeScorer,
    DomainAuthorityScorer,
    FreshnessScorer,
    KeywordScorer,
    PathDepthScorer,
)

# Workshop libs (libs/python/src)
_LIBS_SRC = Path(__file__).resolve().parents[2] / "libs" / "python" / "src"
if str(_LIBS_SRC) not in sys.path:
    sys.path.insert(0, str(_LIBS_SRC))

from workshop.crawl4ai_bridge import crawl_batch, crawl_url  # noqa: E402

server = Server("crawl4ai")
_md_gen = DefaultMarkdownGenerator()


def _check_venv_path() -> tuple[Path, bool]:
    """Synchronous path check — safe to call via asyncio.to_thread."""
    venv_python = Path("~/.venvs/crawl4ai/bin/python").expanduser()
    return venv_python, venv_python.exists()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="crawl4ai_crawl",
            description="Crawl a URL using crawl4ai in isolated venv. Returns markdown content + metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to crawl"},
                    "timeout": {
                        "type": "number",
                        "default": 60.0,
                        "description": "Timeout in seconds",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="crawl4ai_crawl_batch",
            description="Crawl multiple URLs concurrently. Returns list of results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "URLs to crawl",
                    },
                    "max_concurrent": {
                        "type": "integer",
                        "default": 3,
                        "description": "Max concurrent crawls",
                    },
                    "timeout": {
                        "type": "number",
                        "default": 60.0,
                        "description": "Per-URL timeout in seconds",
                    },
                },
                "required": ["urls"],
            },
        ),
        Tool(
            name="crawl4ai_chunk",
            description="Chunk text for embedding using configurable strategies.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to chunk"},
                    "strategy": {
                        "type": "string",
                        "enum": ["sentence", "regex", "fixed", "sliding"],
                        "default": "sentence",
                        "description": "Chunking strategy",
                    },
                    "chunk_size": {
                        "type": "integer",
                        "default": 1000,
                        "description": "Chars per chunk (fixed) or words per window (sliding)",
                    },
                    "overlap": {
                        "type": "integer",
                        "default": 100,
                        "description": "Overlap chars (fixed) or step words (sliding)",
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="crawl4ai_filter_urls",
            description="Filter URLs through a configurable chain (domain allow-list, blocked paths, dedup).",
            inputSchema={
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "URLs to filter",
                    },
                    "domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": 'Allowed domain allow-list (e.g. ["example.com"])',
                    },
                    "blocked_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Regex patterns for blocked URL paths",
                    },
                    "dedup": {
                        "type": "boolean",
                        "default": True,
                        "description": "Remove duplicate URLs",
                    },
                },
                "required": ["urls"],
            },
        ),
        Tool(
            name="crawl4ai_score_urls",
            description="Score and rank URLs by relevance using keyword, depth, authority, and freshness signals.",
            inputSchema={
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "URLs to score",
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords to boost relevant URLs",
                    },
                    "authority_domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "High-authority domains (score 0.9)",
                    },
                },
                "required": ["urls"],
            },
        ),
        Tool(
            name="crawl4ai_html_to_markdown",
            description="Convert raw HTML to clean Markdown using Workshop-native parser.",
            inputSchema={
                "type": "object",
                "properties": {
                    "html": {"type": "string", "description": "Raw HTML string to convert"},
                    "citations": {
                        "type": "boolean",
                        "default": False,
                        "description": "Replace inline links with [N] citation footnotes",
                    },
                },
                "required": ["html"],
            },
        ),
        Tool(
            name="crawl4ai_analyze_url",
            description="Full pipeline: crawl URL → convert to markdown → chunk → score self. Returns structured analysis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to analyze"},
                    "chunk_strategy": {
                        "type": "string",
                        "enum": ["sentence", "regex", "fixed", "sliding"],
                        "default": "sentence",
                        "description": "Chunking strategy for content",
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords used for scoring and analysis context",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="crawl4ai_status",
            description="Check crawl4ai venv availability and report module status.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


def _build_chunker(strategy: str, chunk_size: int, overlap: int):
    match strategy:
        case "regex":
            return RegexChunking()
        case "fixed":
            return FixedLengthChunking(chunk_size=chunk_size, overlap=overlap)
        case "sliding":
            step = max(1, overlap)
            return SlidingWindowChunking(window_size=chunk_size, step=step)
        case _:
            return SentenceChunking()


def _build_scorer(
    keywords: list[str] | None, authority_domains: list[str] | None
) -> CompositeScorer:
    scorers = [PathDepthScorer(optimal_depth=2, weight=0.5), FreshnessScorer(weight=0.5)]
    if keywords:
        scorers.append(KeywordScorer(keywords=keywords, weight=1.5))
    if authority_domains:
        domain_scores = {d.lower(): 0.9 for d in authority_domains}
        scorers.append(DomainAuthorityScorer(domain_scores=domain_scores, weight=1.0))
    return CompositeScorer(scorers=scorers)


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        match name:
            case "crawl4ai_crawl":
                result = await crawl_url(
                    arguments["url"],
                    timeout=arguments.get("timeout", 60.0),
                )
                data = {
                    "url": result.url,
                    "success": result.success,
                    "title": result.title,
                    "markdown_length": len(result.markdown),
                    "markdown_preview": result.markdown[:2000],
                    "links_count": len(result.links),
                    "links": result.links[:20],
                    "metadata": result.metadata,
                    "error": result.error or None,
                }
                return text_result(json_text(data))

            case "crawl4ai_crawl_batch":
                results = await crawl_batch(
                    arguments["urls"],
                    max_concurrent=arguments.get("max_concurrent", 3),
                    timeout=arguments.get("timeout", 60.0),
                )
                data = [
                    {
                        "url": r.url,
                        "success": r.success,
                        "title": r.title,
                        "markdown_length": len(r.markdown),
                        "markdown_preview": r.markdown[:500],
                        "error": r.error or None,
                    }
                    for r in results
                ]
                summary = {
                    "total": len(data),
                    "succeeded": sum(1 for r in data if r["success"]),
                    "failed": sum(1 for r in data if not r["success"]),
                    "results": data,
                }
                return text_result(json_text(summary))

            case "crawl4ai_chunk":
                text = arguments["text"]
                strategy = arguments.get("strategy", "sentence")
                chunk_size = arguments.get("chunk_size", 1000)
                overlap = arguments.get("overlap", 100)
                chunker = _build_chunker(strategy, chunk_size, overlap)
                chunks = chunker.chunk(text)
                return text_result(
                    json_text(
                        {
                            "strategy": strategy,
                            "input_length": len(text),
                            "chunk_count": len(chunks),
                            "chunks": chunks,
                        }
                    )
                )

            case "crawl4ai_filter_urls":
                urls = arguments["urls"]
                filters = []
                if domains := arguments.get("domains"):
                    filters.append(DomainFilter(allowed_domains=domains))
                if blocked := arguments.get("blocked_paths"):
                    filters.append(PathPatternFilter(blocked_patterns=blocked))
                if arguments.get("dedup", True):
                    filters.append(DuplicateFilter())
                chain = FilterChain(filters=filters)
                passed = chain.apply_batch(urls)
                stats = {f: str(s) for f, s in chain.stats_summary().items()}
                return text_result(
                    json_text(
                        {
                            "input_count": len(urls),
                            "passed_count": len(passed),
                            "passed": passed,
                            "filter_stats": stats,
                        }
                    )
                )

            case "crawl4ai_score_urls":
                urls = arguments["urls"]
                keywords = arguments.get("keywords")
                authority_domains = arguments.get("authority_domains")
                scorer = _build_scorer(keywords, authority_domains)
                ranked = scorer.rank(urls)
                return text_result(
                    json_text(
                        {
                            "count": len(ranked),
                            "ranked": [{"url": u, "score": round(s, 4)} for u, s in ranked],
                        }
                    )
                )

            case "crawl4ai_html_to_markdown":
                result = _md_gen.convert(
                    arguments["html"],
                    links_as_citations=arguments.get("citations", False),
                )
                return text_result(
                    json_text(
                        {
                            "title": result.title,
                            "markdown": result.markdown,
                            "links_count": len(result.links),
                            "links": result.links[:50],
                        }
                    )
                )

            case "crawl4ai_analyze_url":
                url = arguments["url"]
                strategy = arguments.get("chunk_strategy", "sentence")
                keywords = arguments.get("keywords", [])

                # Step 1: Crawl
                crawl_result = await crawl_url(url, timeout=60.0)
                if not crawl_result.success:
                    return text_result(
                        json_text(
                            {
                                "url": url,
                                "success": False,
                                "error": crawl_result.error,
                            }
                        )
                    )

                # Step 2: Chunk markdown
                chunker = _build_chunker(strategy, 1000, 100)
                chunks = chunker.chunk(crawl_result.markdown)

                # Step 3: Score URL itself
                scorer = _build_scorer(keywords, None)
                url_score = scorer.score(url)

                # Step 4: Score extracted links
                links = crawl_result.links[:50]
                scored_links = scorer.rank(links) if links else []

                return text_result(
                    json_text(
                        {
                            "url": url,
                            "success": True,
                            "title": crawl_result.title,
                            "url_score": round(url_score, 4),
                            "markdown_length": len(crawl_result.markdown),
                            "chunk_strategy": strategy,
                            "chunk_count": len(chunks),
                            "chunks_preview": chunks[:3],
                            "top_links": [
                                {"url": u, "score": round(s, 4)} for u, s in scored_links[:10]
                            ],
                            "metadata": crawl_result.metadata,
                        }
                    )
                )

            case "crawl4ai_status":
                venv_python, venv_ok = await asyncio.to_thread(_check_venv_path)

                proc = await asyncio.create_subprocess_exec(
                    str(venv_python),
                    "-c",
                    "import crawl4ai; print(crawl4ai.__version__)",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                version = stdout.decode().strip() if proc.returncode == 0 else None

                return text_result(
                    json_text(
                        {
                            "venv_path": str(venv_python),
                            "venv_exists": venv_ok,
                            "crawl4ai_version": version,
                            "crawl4ai_available": version is not None,
                            "error": stderr.decode().strip()[-300:] if not version else None,
                            "shared_modules": {
                                "chunking": "ok",
                                "url_filter": "ok",
                                "url_scorer": "ok",
                                "markdown_gen": "ok",
                            },
                        }
                    )
                )

            case _:
                return text_result(f"Unknown tool: {name}")

    except Exception as e:
        return text_result(f"Error: {type(e).__name__}: {e}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

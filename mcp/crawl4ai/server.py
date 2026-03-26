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

from mcp.server.fastmcp import FastMCP

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
from workshop.mcp_helpers import mcp_error_handler  # noqa: E402

mcp = FastMCP("crawl4ai")
_md_gen = DefaultMarkdownGenerator()


def _check_venv_path() -> tuple[Path, bool]:
    """Synchronous path check — safe to call via asyncio.to_thread."""
    venv_python = Path("~/.venvs/crawl4ai/bin/python").expanduser()
    return venv_python, venv_python.exists()


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


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


@mcp.tool()
@mcp_error_handler("Crawl4AI")
async def crawl4ai_crawl(url: str, timeout: float = 60.0) -> str:
    """Crawl a URL using crawl4ai in isolated venv. Returns markdown content + metadata."""
    result = await crawl_url(url, timeout=timeout)
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
    return json_text(data)


@mcp.tool()
@mcp_error_handler("Crawl4AI")
async def crawl4ai_crawl_batch(
    urls: list[str], max_concurrent: int = 3, timeout: float = 60.0
) -> str:
    """Crawl multiple URLs concurrently with configurable parallelism. Returns markdown content and metadata for each URL."""
    results = await crawl_batch(
        urls,
        max_concurrent=max_concurrent,
        timeout=timeout,
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
    return json_text(summary)


@mcp.tool()
@mcp_error_handler("Crawl4AI")
async def crawl4ai_chunk(
    text: str,
    strategy: str = "sentence",
    chunk_size: int = 1000,
    overlap: int = 100,
) -> str:
    """Split text into chunks for vector embedding. Strategies: sentence, regex, fixed-length, sliding-window. Returns chunk list with metadata."""
    chunker = _build_chunker(strategy, chunk_size, overlap)
    chunks = chunker.chunk(text)
    return json_text(
        {
            "strategy": strategy,
            "input_length": len(text),
            "chunk_count": len(chunks),
            "chunks": chunks,
        }
    )


@mcp.tool()
@mcp_error_handler("Crawl4AI")
async def crawl4ai_filter_urls(
    urls: list[str],
    domains: list[str] | None = None,
    blocked_paths: list[str] | None = None,
    dedup: bool = True,
) -> str:
    """Filter URLs through a configurable chain (domain allow-list, blocked paths, dedup)."""
    filters = []
    if domains:
        filters.append(DomainFilter(allowed_domains=domains))
    if blocked_paths:
        filters.append(PathPatternFilter(blocked_patterns=blocked_paths))
    if dedup:
        filters.append(DuplicateFilter())
    chain = FilterChain(filters=filters)
    passed = chain.apply_batch(urls)
    stats = {f: str(s) for f, s in chain.stats_summary().items()}
    return json_text(
        {
            "input_count": len(urls),
            "passed_count": len(passed),
            "passed": passed,
            "filter_stats": stats,
        }
    )


@mcp.tool()
@mcp_error_handler("Crawl4AI")
async def crawl4ai_score_urls(
    urls: list[str],
    keywords: list[str] | None = None,
    authority_domains: list[str] | None = None,
) -> str:
    """Score and rank URLs by relevance using keyword, depth, authority, and freshness signals."""
    scorer = _build_scorer(keywords, authority_domains)
    ranked = scorer.rank(urls)
    return json_text(
        {
            "count": len(ranked),
            "ranked": [{"url": u, "score": round(s, 4)} for u, s in ranked],
        }
    )


@mcp.tool()
@mcp_error_handler("Crawl4AI")
async def crawl4ai_html_to_markdown(html: str, citations: bool = False) -> str:
    """Convert raw HTML to clean Markdown using Workshop-native parser."""
    result = _md_gen.convert(html, links_as_citations=citations)
    return json_text(
        {
            "title": result.title,
            "markdown": result.markdown,
            "links_count": len(result.links),
            "links": result.links[:50],
        }
    )


@mcp.tool()
@mcp_error_handler("Crawl4AI")
async def crawl4ai_analyze_url(
    url: str,
    chunk_strategy: str = "sentence",
    keywords: list[str] | None = None,
) -> str:
    """Full pipeline: crawl URL → convert to markdown → chunk → score self. Returns structured analysis."""
    if keywords is None:
        keywords = []

    # Step 1: Crawl
    crawl_result = await crawl_url(url, timeout=60.0)
    if not crawl_result.success:
        return json_text(
            {
                "url": url,
                "success": False,
                "error": crawl_result.error,
            }
        )

    # Step 2: Chunk markdown
    chunker = _build_chunker(chunk_strategy, 1000, 100)
    chunks = chunker.chunk(crawl_result.markdown)

    # Step 3: Score URL itself
    scorer = _build_scorer(keywords, None)
    url_score = scorer.score(url)

    # Step 4: Score extracted links
    links = crawl_result.links[:50]
    scored_links = scorer.rank(links) if links else []

    return json_text(
        {
            "url": url,
            "success": True,
            "title": crawl_result.title,
            "url_score": round(url_score, 4),
            "markdown_length": len(crawl_result.markdown),
            "chunk_strategy": chunk_strategy,
            "chunk_count": len(chunks),
            "chunks_preview": chunks[:3],
            "top_links": [
                {"url": u, "score": round(s, 4)} for u, s in scored_links[:10]
            ],
            "metadata": crawl_result.metadata,
        }
    )


@mcp.tool()
@mcp_error_handler("Crawl4AI")
async def crawl4ai_status() -> str:
    """Check crawl4ai venv availability and report module status."""
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

    return json_text(
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


if __name__ == "__main__":
    mcp.run()

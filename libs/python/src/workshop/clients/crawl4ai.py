"""Crawl4AI SDK client — high-level wrapper for Workshop crawling utilities.

Wraps the crawl4ai subprocess bridge and shared utilities (chunking, URL filtering,
URL scoring, markdown generation) into a single, ergonomic async API.

Usage::

    import asyncio
    from workshop.clients.crawl4ai import Crawl4AIClient

    client = Crawl4AIClient()

    # Crawl a single URL
    result = asyncio.run(client.crawl("https://example.com"))
    print(result.title, result.markdown[:200])

    # Crawl several URLs concurrently (max 3 at a time)
    results = asyncio.run(client.crawl_batch(["https://a.com", "https://b.com"]))

    # Chunk extracted text for embedding
    chunks = client.chunk_text(result.markdown, strategy="sentence")

    # Filter noisy link lists
    clean = client.filter_urls(result.links, domains=["docs.python.org"], dedup=True)

    # Score / rank URLs by keyword relevance
    ranked = client.score_urls(result.links, keywords=["async", "python"])

    # Convert raw HTML to Markdown with citation footnotes
    md = client.html_to_markdown("<h1>Hello</h1><p>World</p>", citations=True)
"""

from __future__ import annotations

from typing import Any

# Shared utilities
from core.src.shared.chunking import (
    ChunkingStrategy,
    FixedLengthChunking,
    RegexChunking,
    SentenceChunking,
    SlidingWindowChunking,
)
from core.src.shared.markdown_gen import DefaultMarkdownGenerator, MarkdownResult
from core.src.shared.url_filter import (
    DomainFilter,
    DuplicateFilter,
    FilterChain,
    PathPatternFilter,
)
from core.src.shared.url_scorer import (
    CompositeScorer,
    DomainAuthorityScorer,
    KeywordScorer,
)

# Bridge — subprocess protocol to isolated crawl4ai venv
from workshop.crawl4ai_bridge import CrawlResult
from workshop.crawl4ai_bridge import crawl_batch as _crawl_batch
from workshop.crawl4ai_bridge import crawl_url as _crawl_url

__all__ = [
    "ChunkingStrategy",
    "Crawl4AIClient",
    "CrawlResult",
    "MarkdownResult",
]

_STRATEGY_MAP: dict[str, type[ChunkingStrategy]] = {
    "sentence": SentenceChunking,
    "fixed": FixedLengthChunking,
    "sliding": SlidingWindowChunking,
    "regex": RegexChunking,
}


class Crawl4AIClient:
    """High-level crawl4ai SDK client for Workshop.

    Provides async crawling via the isolated crawl4ai venv (AD-12) plus
    synchronous text processing utilities from Workshop shared modules.

    All methods are stateless — safe to share across threads/tasks.
    """

    # ------------------------------------------------------------------ crawl

    async def crawl(self, url: str, *, timeout: float = 60.0) -> CrawlResult:  # noqa: ASYNC109
        """Crawl a single URL and return structured markdown + metadata.

        Args:
            url: Target URL.
            timeout: Subprocess timeout in seconds.

        Returns:
            CrawlResult with .markdown, .title, .links, .success, .error.
        """
        return await _crawl_url(url, timeout=timeout)

    async def crawl_batch(
        self,
        urls: list[str],
        *,
        max_concurrent: int = 3,
        timeout: float = 60.0,  # noqa: ASYNC109
    ) -> list[CrawlResult]:
        """Crawl multiple URLs with bounded concurrency.

        Args:
            urls: List of target URLs.
            max_concurrent: Maximum parallel subprocess workers.
            timeout: Per-URL subprocess timeout in seconds.

        Returns:
            List of CrawlResult in the same order as *urls*.
        """
        return await _crawl_batch(urls, max_concurrent=max_concurrent, timeout=timeout)

    # ------------------------------------------------------------------ chunk

    def chunk_text(
        self,
        text: str,
        strategy: str = "sentence",
        **kwargs: Any,
    ) -> list[str]:
        """Split text into chunks using the named strategy.

        Args:
            text: Input text (typically CrawlResult.markdown).
            strategy: One of ``sentence``, ``fixed``, ``sliding``, ``regex``.
            **kwargs: Forwarded to the strategy constructor
                (e.g. ``chunk_size=500``, ``overlap=50``).

        Returns:
            List of non-empty string chunks.

        Raises:
            ValueError: If *strategy* is not recognised.
        """
        cls = _STRATEGY_MAP.get(strategy)
        if cls is None:
            raise ValueError(f"Unknown strategy {strategy!r}. Choose from: {list(_STRATEGY_MAP)}")
        return cls(**kwargs).chunk(text)

    # ------------------------------------------------------------------ filter

    def filter_urls(
        self,
        urls: list[str],
        *,
        domains: list[str] | None = None,
        blocked_paths: list[str] | None = None,
        dedup: bool = True,
    ) -> list[str]:
        """Filter a URL list using domain allowlist, path patterns, and dedup.

        Args:
            urls: Raw URL list (e.g. from CrawlResult.links).
            domains: If set, only URLs from these domains pass.
            blocked_paths: Regex patterns matched against URL path; matches drop.
            dedup: Remove duplicate URLs when True (default).

        Returns:
            Filtered list preserving original order.
        """
        filters = []
        if domains:
            filters.append(DomainFilter(allowed_domains=domains))
        if blocked_paths:
            filters.append(PathPatternFilter(blocked_patterns=blocked_paths))
        if dedup:
            filters.append(DuplicateFilter())
        if not filters:
            return list(urls)
        return FilterChain(filters=filters).apply_batch(urls)

    # ------------------------------------------------------------------ score

    def score_urls(
        self,
        urls: list[str],
        *,
        keywords: list[str] | None = None,
        authority_domains: dict[str, float] | None = None,
    ) -> list[tuple[str, float]]:
        """Score and rank URLs by keyword relevance and/or domain authority.

        Args:
            urls: URL list to rank.
            keywords: Terms to look for in each URL string.
            authority_domains: Mapping of domain → score in [0, 1].

        Returns:
            List of (url, score) pairs sorted highest-first.
        """
        scorers = []
        if keywords:
            scorers.append(KeywordScorer(keywords=keywords))
        if authority_domains:
            scorers.append(DomainAuthorityScorer(domain_scores=authority_domains))
        if not scorers:
            return [(u, 0.0) for u in urls]
        return CompositeScorer(scorers=scorers).rank(urls)

    # ------------------------------------------------------------------ html

    def html_to_markdown(self, html: str, *, citations: bool = False) -> MarkdownResult:
        """Convert raw HTML to Markdown.

        Args:
            html: Raw HTML string.
            citations: Replace inline links with numbered footnotes [N].

        Returns:
            MarkdownResult with .markdown, .links, .title.
        """
        return DefaultMarkdownGenerator().convert(html, links_as_citations=citations)


# Module-level singleton for convenience
default_client = Crawl4AIClient()

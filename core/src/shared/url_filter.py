"""URL filter chain for Workshop crawling / intelflow pipelines.

Design inspired by crawl4ai's deep_crawling/filters.py and aligned with
AD-12 (Intelflow feed hygiene).  Zero external dependencies — stdlib only.

Usage::

    chain = FilterChain([
        DomainFilter(allowed_domains=["example.com"]),
        PathPatternFilter(blocked_patterns=[r"/login", r"/admin"]),
        DuplicateFilter(),
        DepthFilter(max_depth=4),
    ])
    urls = chain.apply_batch(raw_urls)
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class FilterStats:
    """Lightweight per-filter counters."""

    total: int = 0
    passed: int = 0
    rejected: int = 0

    def record(self, passed: bool) -> None:
        self.total += 1
        if passed:
            self.passed += 1
        else:
            self.rejected += 1

    def __repr__(self) -> str:
        return f"FilterStats(total={self.total}, passed={self.passed}, rejected={self.rejected})"


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class URLFilter(ABC):
    """Abstract URL filter.  True = keep the URL, False = drop it."""

    name: str = "URLFilter"

    def __init__(self) -> None:
        self.stats: FilterStats = FilterStats()

    @abstractmethod
    def apply(self, url: str, **context: object) -> bool:
        """Return True to keep *url*, False to discard it."""

    def _record(self, result: bool) -> bool:
        self.stats.record(result)
        return result


@dataclass
class FilterChain:
    """AND-chain of URLFilters.  All must pass for a URL to be kept."""

    filters: list[URLFilter] = field(default_factory=list)

    def apply(self, url: str, **context: object) -> bool:
        """Return True only if every filter passes."""
        for f in self.filters:
            if not f.apply(url, **context):
                return False
        return True

    def apply_batch(self, urls: list[str], **context: object) -> list[str]:
        """Return the subset of *urls* that pass all filters."""
        return [u for u in urls if self.apply(u, **context)]

    def stats_summary(self) -> dict[str, FilterStats]:
        return {f.name: f.stats for f in self.filters}


class DomainFilter(URLFilter):
    """Whitelist and/or blacklist by hostname (subdomain-aware).

    *allowed_domains*: if set, only these domains (and their subdomains) pass.
    *blocked_domains*: these domains (and their subdomains) are always dropped.
    """

    name = "DomainFilter"
    _DOMAIN_RE = re.compile(r"://([^/?#]+)")

    def __init__(
        self,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._allowed = frozenset(d.lower() for d in allowed_domains) if allowed_domains else None
        self._blocked = (
            frozenset(d.lower() for d in blocked_domains) if blocked_domains else frozenset()
        )

    @staticmethod
    def _host(url: str) -> str:
        m = re.search(r"://([^/?#]+)", url)
        return m.group(1).lower() if m else ""

    @staticmethod
    def _matches(host: str, domain: str) -> bool:
        return host == domain or host.endswith(f".{domain}")

    def apply(self, url: str, **context: object) -> bool:
        host = self._host(url)
        if any(self._matches(host, b) for b in self._blocked):
            return self._record(False)
        if self._allowed is not None and not any(self._matches(host, a) for a in self._allowed):
            return self._record(False)
        return self._record(True)


class PathPatternFilter(URLFilter):
    """Drop URLs whose path matches any of the *blocked_patterns* regexes."""

    name = "PathPatternFilter"

    def __init__(self, blocked_patterns: list[str]) -> None:
        super().__init__()
        self._patterns = [re.compile(p) for p in blocked_patterns]

    def apply(self, url: str, **context: object) -> bool:
        path = urlparse(url).path
        if any(p.search(path) for p in self._patterns):
            return self._record(False)
        return self._record(True)


class ContentTypeFilter(URLFilter):
    """Keep only URLs whose file extension implies an allowed MIME category.

    URLs with no extension are always kept (assumed HTML / dynamic).
    Pass *allowed_extensions* as lowercase extensions without dots, e.g.
    ``["html", "htm", "pdf"]``.
    """

    name = "ContentTypeFilter"

    def __init__(self, allowed_extensions: list[str]) -> None:
        super().__init__()
        self._allowed = frozenset(e.lower().lstrip(".") for e in allowed_extensions)

    def apply(self, url: str, **context: object) -> bool:
        path = urlparse(url).path.split("?")[0]
        ext = path.rsplit(".", 1)[-1].lower() if "." in path.rsplit("/", 1)[-1] else ""
        if ext and ext not in self._allowed:
            return self._record(False)
        return self._record(True)


class DuplicateFilter(URLFilter):
    """Drop URLs already seen in this filter's lifetime (set-based dedup)."""

    name = "DuplicateFilter"

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[str] = set()

    def apply(self, url: str, **context: object) -> bool:
        if url in self._seen:
            return self._record(False)
        self._seen.add(url)
        return self._record(True)


class DepthFilter(URLFilter):
    """Drop URLs whose path depth exceeds *max_depth* segments.

    ``https://example.com/a/b/c`` has depth 3.
    """

    name = "DepthFilter"

    def __init__(self, max_depth: int) -> None:
        super().__init__()
        self.max_depth = max_depth

    def apply(self, url: str, **context: object) -> bool:
        path = urlparse(url).path
        depth = len([s for s in path.split("/") if s])
        return self._record(depth <= self.max_depth)

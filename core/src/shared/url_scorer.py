"""URL Scorer — relevance scoring primitives for URL ranking.

Inspired by crawl4ai's deep-crawling scorer design
(vendor/crawl4ai/crawl4ai/deep_crawling/scorers.py).
Follows Workshop AD-12: reusable shared utilities extracted from external tool integrations.

Usage::

    scorer = CompositeScorer([
        KeywordScorer(["python", "tutorial"], weight=1.5),
        PathDepthScorer(optimal_depth=2),
        FreshnessScorer(),
    ])
    ranked = scorer.rank(["https://example.com/python/tutorial/2024/intro"])
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------


class URLScorer(ABC):
    """Abstract base for URL relevance scorers.

    Each scorer returns a float in [0.0, 1.0] representing how relevant a URL
    is for a given purpose.  The ``weight`` attribute scales the contribution
    when used inside a ``CompositeScorer``.
    """

    weight: float = 1.0
    name: str = "base"

    @abstractmethod
    def score(self, url: str, **context: object) -> float:
        """Return relevance score in [0.0, 1.0]."""


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------


@dataclass
class CompositeScorer:
    """Combine multiple URLScorers via weighted average.

    Args:
        scorers: List of URLScorer instances.
    """

    scorers: list[URLScorer]

    def score(self, url: str, **context: object) -> float:
        """Weighted average score across all child scorers."""
        if not self.scorers:
            return 0.0
        total_weight = sum(s.weight for s in self.scorers)
        if total_weight == 0.0:
            return 0.0
        weighted_sum = sum(s.score(url, **context) * s.weight for s in self.scorers)
        return min(1.0, max(0.0, weighted_sum / total_weight))

    def rank(self, urls: list[str], **context: object) -> list[tuple[str, float]]:
        """Score every URL and return sorted (url, score) pairs, highest first."""
        scored = [(url, self.score(url, **context)) for url in urls]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored


# ---------------------------------------------------------------------------
# Concrete scorers
# ---------------------------------------------------------------------------


@dataclass
class KeywordScorer(URLScorer):
    """Score URLs by keyword presence (case-insensitive substring match).

    Score = matched_keywords / total_keywords, so having all keywords → 1.0.
    Zero keywords configured always returns 0.0.
    """

    keywords: list[str]
    weight: float = 1.0
    name: str = "keyword"

    def score(self, url: str, **context: object) -> float:
        if not self.keywords:
            return 0.0
        lower = url.lower()
        hits = sum(1 for kw in self.keywords if kw.lower() in lower)
        return hits / len(self.keywords)


@dataclass
class PathDepthScorer(URLScorer):
    """Prefer URLs whose path depth is close to ``optimal_depth``.

    Score degrades the further the actual depth deviates from the optimum,
    using an inverse-distance function capped at 1.0.
    """

    optimal_depth: int = 2
    weight: float = 1.0
    name: str = "path_depth"

    @staticmethod
    def _path_depth(path: str) -> int:
        """Count non-empty path segments."""
        return len([seg for seg in path.split("/") if seg])

    def score(self, url: str, **context: object) -> float:
        try:
            path = urlparse(url).path
        except Exception:
            return 0.5
        depth = self._path_depth(path)
        distance = abs(depth - self.optimal_depth)
        if distance == 0:
            return 1.0
        return 1.0 / (1.0 + distance)


@dataclass
class DomainAuthorityScorer(URLScorer):
    """Assign authority scores to known domains.

    Unknown domains receive ``default_score``.

    Args:
        domain_scores: Mapping of lowercase domain → score in [0.0, 1.0].
        default_score: Fallback for unknown domains (default 0.3).
    """

    domain_scores: dict[str, float]
    default_score: float = 0.3
    weight: float = 1.0
    name: str = "domain_authority"

    def _extract_domain(self, url: str) -> str:
        try:
            return urlparse(url).hostname or ""
        except Exception:
            return ""

    def score(self, url: str, **context: object) -> float:
        domain = self._extract_domain(url).lower()
        # Also check registered domain (strip leading subdomains)
        parts = domain.split(".")
        for i in range(len(parts)):
            candidate = ".".join(parts[i:])
            if candidate in self.domain_scores:
                return self.domain_scores[candidate]
        return self.default_score


_DATE_RE = re.compile(r"(?:/|[-_])((?:19|20)\d{2})(?:(?:/|[-_])\d{2}(?:(?:/|[-_])\d{2})?)?")
_CURRENT_YEAR = datetime.now().year
_FRESHNESS_TABLE = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5]


@dataclass
class FreshnessScorer(URLScorer):
    """Score URLs that contain date patterns (YYYY, YYYY/MM, YYYY-MM-DD, etc.).

    More recent years score higher.  URLs with no detectable date return
    ``no_date_score`` (default 0.5 — neutral).
    """

    current_year: int = field(default_factory=lambda: _CURRENT_YEAR)
    no_date_score: float = 0.5
    weight: float = 1.0
    name: str = "freshness"

    def _extract_year(self, url: str) -> int | None:
        latest: int | None = None
        for m in _DATE_RE.finditer(url):
            y = int(m.group(1))
            if y <= self.current_year and (latest is None or y > latest):
                latest = y
        return latest

    def score(self, url: str, **context: object) -> float:
        year = self._extract_year(url)
        if year is None:
            return self.no_date_score
        diff = self.current_year - year
        if diff < len(_FRESHNESS_TABLE):
            return _FRESHNESS_TABLE[diff]
        return max(0.1, 1.0 - diff * 0.1)

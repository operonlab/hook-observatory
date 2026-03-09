"""Tests for crawl4ai-inspired shared utilities (AD-12 batch 1).

Covers:
- RateLimiter           (src/shared/rate_limiter.py)
- Chunking strategies   (src/shared/chunking.py)
- URL filters           (src/shared/url_filter.py)
- URL scorers           (src/shared/url_scorer.py)
- MarkdownGenerator     (src/shared/markdown_gen.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ===========================================================================
# TestRateLimiter
# ===========================================================================


class TestRateLimiter:
    def _make(self, **kwargs):
        from src.shared.rate_limiter import RateLimiter

        kwargs.setdefault("base_delay", (0.0, 0.0))
        return RateLimiter(**kwargs)

    @pytest.mark.asyncio
    async def test_acquire_creates_domain_state(self):
        """acquire() initialises per-domain state on first call."""
        rl = self._make()
        url = "https://example.com/page"
        await rl.acquire(url)
        assert "example.com" in rl._domains

    @pytest.mark.asyncio
    async def test_report_failure_increases_delay(self):
        """report_failure() with a 429 code increases current_delay."""
        rl = self._make(base_delay=(1.0, 1.0), backoff_factor=2.0)
        url = "https://slow.io/api"
        await rl.acquire(url)
        state = rl._domains["slow.io"]
        before = state.current_delay
        rl.report_failure(url, 429)
        assert state.current_delay >= before  # must not decrease
        assert state.fail_count == 1

    @pytest.mark.asyncio
    async def test_report_success_decreases_delay(self):
        """report_success() reduces delay toward the base floor."""
        from src.shared.rate_limiter import RateLimiter

        rl = RateLimiter(base_delay=(0.0, 0.0), backoff_factor=2.0, max_delay=60.0)
        url = "https://fast.io/api"
        await rl.acquire(url)
        state = rl._domains["fast.io"]
        # Manually set a high delay to simulate prior failures
        state.current_delay = 10.0
        rl.report_success(url)
        assert state.current_delay < 10.0
        assert state.success_count == 1
        assert state.fail_count == 0

    @pytest.mark.asyncio
    async def test_429_triggers_backoff_capped_at_max_delay(self):
        """report_failure() with 429 respects max_delay ceiling."""
        from src.shared.rate_limiter import RateLimiter

        rl = RateLimiter(base_delay=(50.0, 50.0), backoff_factor=10.0, max_delay=60.0)
        url = "https://ratelimited.com/"
        await rl.acquire(url)
        rl.report_failure(url, 429)
        state = rl._domains["ratelimited.com"]
        assert state.current_delay <= 60.0


# ===========================================================================
# TestChunking
# ===========================================================================


class TestChunking:
    def test_regex_chunking_splits_paragraphs(self):
        from src.shared.chunking import RegexChunking

        text = "First paragraph.\n\nSecond paragraph.\n\nThird one."
        chunks = RegexChunking().chunk(text)
        assert len(chunks) == 3
        assert chunks[0] == "First paragraph."

    def test_fixed_length_chunking_size_and_overlap(self):
        from src.shared.chunking import FixedLengthChunking

        text = "A" * 250
        chunker = FixedLengthChunking(chunk_size=100, overlap=20)
        chunks = chunker.chunk(text)
        # Each chunk ≤ 100 chars
        assert all(len(c) <= 100 for c in chunks)
        # Consecutive chunks share overlap characters
        assert chunks[0][-20:] == chunks[1][:20]

    def test_sliding_window_chunking_creates_overlaps(self):
        from src.shared.chunking import SlidingWindowChunking

        words = list(range(200))
        text = " ".join(str(w) for w in words)
        chunker = SlidingWindowChunking(window_size=10, step=5)
        chunks = chunker.chunk(text)
        assert len(chunks) > 1
        # Words at overlap position appear in consecutive chunks
        first_words = set(chunks[0].split())
        second_words = set(chunks[1].split())
        assert first_words & second_words  # non-empty intersection

    def test_sentence_chunking_splits_at_boundaries(self):
        from src.shared.chunking import SentenceChunking

        text = "The quick brown fox jumps. A second sentence follows! And a third?"
        chunks = SentenceChunking(min_length=5).chunk(text)
        assert len(chunks) >= 2
        assert any("quick brown fox" in c for c in chunks)

    def test_empty_input_returns_empty_list(self):
        from src.shared.chunking import (
            FixedLengthChunking,
            RegexChunking,
            SentenceChunking,
            SlidingWindowChunking,
        )

        for cls in (RegexChunking, SentenceChunking):
            result = cls().chunk("")
            assert result == [], f"{cls.__name__} should return [] for empty input"

        assert FixedLengthChunking(chunk_size=50, overlap=0).chunk("") == []
        assert SlidingWindowChunking(window_size=10, step=5).chunk("") == []


# ===========================================================================
# TestURLFilter
# ===========================================================================


class TestURLFilter:
    def test_domain_filter_whitelist(self):
        from src.shared.url_filter import DomainFilter

        f = DomainFilter(allowed_domains=["example.com"])
        assert f.apply("https://example.com/page") is True
        assert f.apply("https://sub.example.com/x") is True
        assert f.apply("https://other.org/page") is False

    def test_domain_filter_blacklist(self):
        from src.shared.url_filter import DomainFilter

        f = DomainFilter(blocked_domains=["evil.com"])
        assert f.apply("https://safe.io/page") is True
        assert f.apply("https://evil.com/anything") is False
        assert f.apply("https://sub.evil.com/anything") is False

    def test_path_pattern_filter_blocks_admin(self):
        from src.shared.url_filter import PathPatternFilter

        f = PathPatternFilter(blocked_patterns=[r"/admin", r"/login"])
        assert f.apply("https://site.com/articles/1") is True
        assert f.apply("https://site.com/admin/settings") is False
        assert f.apply("https://site.com/login") is False

    def test_duplicate_filter_deduplicates(self):
        from src.shared.url_filter import DuplicateFilter

        f = DuplicateFilter()
        url = "https://example.com/page"
        assert f.apply(url) is True
        assert f.apply(url) is False  # duplicate
        assert f.apply("https://example.com/other") is True

    def test_filter_chain_and_logic(self):
        from src.shared.url_filter import (
            DomainFilter,
            DuplicateFilter,
            FilterChain,
            PathPatternFilter,
        )

        chain = FilterChain(
            filters=[
                DomainFilter(allowed_domains=["example.com"]),
                PathPatternFilter(blocked_patterns=[r"/admin"]),
                DuplicateFilter(),
            ]
        )
        urls = [
            "https://example.com/articles/1",
            "https://example.com/admin/settings",  # blocked by path
            "https://other.org/page",  # blocked by domain
            "https://example.com/articles/1",  # duplicate
            "https://example.com/articles/2",
        ]
        result = chain.apply_batch(urls)
        assert "https://example.com/articles/1" in result
        assert "https://example.com/articles/2" in result
        assert "https://example.com/admin/settings" not in result
        assert "https://other.org/page" not in result
        assert result.count("https://example.com/articles/1") == 1

    def test_filter_stats_counting(self):
        from src.shared.url_filter import DomainFilter

        f = DomainFilter(allowed_domains=["good.com"])
        f.apply("https://good.com/a")
        f.apply("https://bad.com/b")
        f.apply("https://good.com/c")
        assert f.stats.total == 3
        assert f.stats.passed == 2
        assert f.stats.rejected == 1


# ===========================================================================
# TestURLScorer
# ===========================================================================


class TestURLScorer:
    def test_keyword_scorer_matches(self):
        from src.shared.url_scorer import KeywordScorer

        scorer = KeywordScorer(keywords=["python", "tutorial"], weight=1.0)
        high = scorer.score("https://example.com/python/tutorial/intro")
        low = scorer.score("https://example.com/java/basics")
        assert high == 1.0
        assert low == 0.0

    def test_path_depth_scorer_prefers_optimal(self):
        from src.shared.url_scorer import PathDepthScorer

        scorer = PathDepthScorer(optimal_depth=2)
        perfect = scorer.score("https://example.com/a/b")  # depth 2
        deep = scorer.score("https://example.com/a/b/c/d/e")  # depth 5
        assert perfect == 1.0
        assert deep < perfect

    def test_composite_scorer_weighted_average(self):
        from src.shared.url_scorer import CompositeScorer, KeywordScorer, PathDepthScorer

        composite = CompositeScorer(
            scorers=[
                KeywordScorer(keywords=["docs"], weight=2.0),
                PathDepthScorer(optimal_depth=1, weight=1.0),
            ]
        )
        score = composite.score("https://example.com/docs")
        assert 0.0 <= score <= 1.0

    def test_rank_returns_sorted_descending(self):
        from src.shared.url_scorer import CompositeScorer, KeywordScorer

        scorer = CompositeScorer(scorers=[KeywordScorer(keywords=["news"], weight=1.0)])
        urls = [
            "https://example.com/sports",
            "https://example.com/news/today",
            "https://example.com/news/archive",
        ]
        ranked = scorer.rank(urls)
        assert len(ranked) == 3
        # Top two should be news URLs (score 1.0), sports last (score 0.0)
        scores = [score for _, score in ranked]
        assert scores == sorted(scores, reverse=True)
        assert ranked[0][0] in (
            "https://example.com/news/today",
            "https://example.com/news/archive",
        )


# ===========================================================================
# TestMarkdownGen
# ===========================================================================


class TestMarkdownGen:
    def _gen(self):
        from src.shared.markdown_gen import DefaultMarkdownGenerator

        return DefaultMarkdownGenerator()

    def test_basic_html_to_markdown(self):
        """Heading, paragraph, and link are all converted."""
        gen = self._gen()
        html = "<h1>Title</h1><p>Hello <a href='https://example.com'>world</a>.</p>"
        result = gen.convert(html)
        assert "# Title" in result.markdown
        assert "Hello" in result.markdown
        assert "[world](https://example.com)" in result.markdown

    def test_links_as_citations(self):
        """links_as_citations replaces inline links with [N] footnotes."""
        gen = self._gen()
        html = "<p><a href='https://a.com'>A</a> and <a href='https://b.com'>B</a></p>"
        result = gen.convert(html, links_as_citations=True)
        assert "[1]" in result.markdown
        assert "[2]" in result.markdown
        assert "https://a.com" in result.links
        assert "https://b.com" in result.links

    def test_strip_tags_removes_script_and_style(self):
        """script and style tags (default strip) are excluded from output."""
        gen = self._gen()
        html = "<p>Visible</p><script>alert('xss')</script><style>.h{}</style>"
        result = gen.convert(html)
        assert "Visible" in result.markdown
        assert "alert" not in result.markdown
        assert ".h{}" not in result.markdown

    def test_markdown_result_contains_links_and_title(self):
        """MarkdownResult exposes links list (citations mode) and page title."""
        gen = self._gen()
        html = "<title>My Page</title><a href='https://x.com/p'>link</a>"
        # links list is populated only when links_as_citations=True
        result = gen.convert(html, links_as_citations=True)
        assert result.title == "My Page"
        assert "https://x.com/p" in result.links

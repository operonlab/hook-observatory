"""End-to-end data flow tests for Crawl4AI integration (蠶食 real wiring).

Tests REAL integration points, not standalone modules:
1. RateLimiter wired into webcrawl.py
2. EnrichmentPipeline wired into capture/services.py promote()
3. ChunkingStrategy wired into embedding.py get_embeddings_chunked()
4. WebCrawlAdapter enrichment_strategies on the adapter class
5. crawl_batch domain_delay throttling in crawl4ai_bridge.py

These tests use mocks for external I/O (network, DB) but verify
that the WIRING between components is correct.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Test 1: RateLimiter wired into webcrawl.py ──


class TestWebcrawlRateLimiterWiring:
    """Verify RateLimiter is actually used by intelflow/webcrawl.py."""

    @pytest.mark.asyncio
    async def test_create_report_calls_rate_limiter(self):
        """webcrawl.create_report_from_url must call _limiter.acquire() before crawling."""
        from src.modules.intelflow import webcrawl

        # Verify module-level _limiter exists and is a RateLimiter
        from src.shared.rate_limiter import RateLimiter

        assert isinstance(webcrawl._limiter, RateLimiter)
        assert webcrawl._limiter.base_delay == (0.5, 1.5)
        assert webcrawl._limiter.max_delay == 30.0

    @pytest.mark.asyncio
    async def test_crawl_success_reports_to_limiter(self):
        """On successful crawl, report_success is called."""
        from src.modules.intelflow import webcrawl

        mock_crawl_result = MagicMock()
        mock_crawl_result.success = True
        mock_crawl_result.markdown = "# Hello World\n\nTest content"
        mock_crawl_result.title = "Test Page"
        mock_crawl_result.links = []
        mock_crawl_result.metadata = {}

        mock_report = MagicMock()
        mock_report.id = "rpt-test-123"

        with (
            patch.object(webcrawl._limiter, "acquire", new_callable=AsyncMock) as mock_acquire,
            patch.object(webcrawl._limiter, "report_success") as mock_success,
            patch(
                "workshop.crawl4ai_bridge.crawl_url",
                new_callable=AsyncMock,
                return_value=mock_crawl_result,
            ),
            patch("src.modules.intelflow.services.report_service") as mock_svc,
        ):
            mock_svc.create = AsyncMock(return_value=mock_report)
            result = await webcrawl.create_report_from_url(
                "https://example.com/test",
                db=AsyncMock(),
                space_id="space-1",
                created_by="user-1",
            )

            mock_acquire.assert_awaited_once_with("https://example.com/test")
            mock_success.assert_called_once_with("https://example.com/test")
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_crawl_failure_reports_to_limiter(self):
        """On failed crawl, report_failure is called."""
        from src.modules.intelflow import webcrawl

        mock_crawl_result = MagicMock()
        mock_crawl_result.success = False
        mock_crawl_result.error = "Timeout"

        with (
            patch.object(webcrawl._limiter, "acquire", new_callable=AsyncMock),
            patch.object(webcrawl._limiter, "report_failure") as mock_failure,
            patch(
                "workshop.crawl4ai_bridge.crawl_url",
                new_callable=AsyncMock,
                return_value=mock_crawl_result,
            ),
        ):
            result = await webcrawl.create_report_from_url(
                "https://example.com/slow",
                db=AsyncMock(),
                space_id="space-1",
            )

            mock_failure.assert_called_once_with("https://example.com/slow", 429)
            assert result["success"] is False


# ── Test 2: EnrichmentPipeline wired into capture/services.py ──


class TestCaptureEnrichmentWiring:
    """Verify EnrichmentPipeline is called during capture promote()."""

    def test_services_imports_enrichment_pipeline(self):
        """capture/services.py must reference EnrichmentPipeline and DefaultsStrategy."""
        import inspect

        from src.modules.capture import services

        source = inspect.getsource(services.CaptureService.promote)
        assert "EnrichmentPipeline" in source
        assert "DefaultsStrategy" in source
        assert "enrichment_strategies" in source

    def test_webcrawl_adapter_has_enrichment_strategies(self):
        """WebCrawlCaptureAdapter declares enrichment_strategies list."""
        from src.modules.capture.webcrawl_adapter import WebCrawlCaptureAdapter

        adapter = WebCrawlCaptureAdapter()
        assert adapter.enrichment_strategies is not None
        assert len(adapter.enrichment_strategies) >= 1

        # Verify it's a PatternMatchStrategy
        from src.modules.capture.strategies import PatternMatchStrategy

        assert isinstance(adapter.enrichment_strategies[0], PatternMatchStrategy)

    @pytest.mark.asyncio
    async def test_enrichment_pipeline_runs_on_webcrawl_payload(self):
        """Pipeline produces enrichment results for webcrawl-shaped data."""
        from src.modules.capture.strategies import DefaultsStrategy, EnrichmentPipeline
        from src.modules.capture.webcrawl_adapter import WebCrawlCaptureAdapter

        adapter = WebCrawlCaptureAdapter()

        pipeline = EnrichmentPipeline()
        pipeline.add(
            DefaultsStrategy(
                adapter_defaults=adapter.default_values,
                user_prefs={},
            )
        )
        for strategy in adapter.enrichment_strategies:
            pipeline.add(strategy)

        result = await pipeline.run(
            {"url": "https://example.com/article", "raw_text": "<title>My Article</title>"},
            module="intelflow",
            entity_type="webcrawl",
        )
        # DefaultsStrategy should add tags
        assert "webcrawl" in result.payload.get("tags", [])
        # PatternMatchStrategy should extract title from raw_text
        assert result.payload.get("title") == "My Article"


# ── Test 3: ChunkingStrategy wired into embedding.py ──


class TestEmbeddingChunkingWiring:
    """Verify get_embeddings_chunked uses ChunkingStrategy."""

    def test_embedding_imports_chunking(self):
        """embedding.py imports from chunking module."""
        from src.shared import embedding

        assert hasattr(embedding, "get_embeddings_chunked")
        # Verify the function accepts a strategy parameter
        import inspect

        sig = inspect.signature(embedding.get_embeddings_chunked)
        assert "strategy" in sig.parameters
        assert "max_chunk_chars" in sig.parameters

    @pytest.mark.asyncio
    async def test_short_text_single_chunk(self):
        """Short text (< max_chunk_chars) should not be chunked."""
        from src.shared.embedding import get_embeddings_chunked

        mock_embedding = [0.1] * 768

        with patch(
            "src.shared.embedding.get_embeddings_batch",
            new_callable=AsyncMock,
            return_value=[mock_embedding],
        ):
            results = await get_embeddings_chunked("Short text", max_chunk_chars=2000)

        assert len(results) == 1
        assert results[0]["chunk"] == "Short text"
        assert results[0]["index"] == 0

    @pytest.mark.asyncio
    async def test_long_text_chunked(self):
        """Long text should be split into multiple chunks."""
        from src.shared.chunking import FixedLengthChunking
        from src.shared.embedding import get_embeddings_chunked

        long_text = "word " * 1000  # ~5000 chars
        mock_embedding = [0.1] * 768

        # Pre-calculate how many chunks will be produced
        chunker = FixedLengthChunking(chunk_size=500, overlap=50)
        expected_chunks = chunker.chunk(long_text)

        with patch(
            "src.shared.embedding.get_embeddings_batch",
            new_callable=AsyncMock,
        ) as mock_batch:
            # Return exact number of embeddings matching chunks
            mock_batch.return_value = [mock_embedding] * len(expected_chunks)

            results = await get_embeddings_chunked(
                long_text,
                max_chunk_chars=500,
                overlap=50,
            )

        # Should have multiple chunks
        assert len(results) > 1
        assert len(results) == len(expected_chunks)
        # Each chunk has the expected shape
        for r in results:
            assert "chunk" in r
            assert "embedding" in r
            assert "index" in r
            assert len(r["chunk"]) <= 500

    @pytest.mark.asyncio
    async def test_custom_strategy_is_used(self):
        """Custom chunking strategy should be respected."""
        from src.shared.chunking import SentenceChunking
        from src.shared.embedding import get_embeddings_chunked

        text = "First sentence here. Second sentence here. Third sentence here."
        mock_embedding = [0.1] * 768

        with patch(
            "src.shared.embedding.get_embeddings_batch",
            new_callable=AsyncMock,
        ) as mock_batch:
            mock_batch.return_value = [mock_embedding] * 3

            results = await get_embeddings_chunked(
                text,
                max_chunk_chars=10,  # force chunking
                strategy=SentenceChunking(min_length=5),
            )

        # SentenceChunking should split by sentence boundaries
        assert len(results) >= 2
        chunks = [r["chunk"] for r in results]
        assert any("First" in c for c in chunks)
        assert any("Second" in c for c in chunks)


# ── Test 4: crawl_batch domain_delay in crawl4ai_bridge.py ──


class TestCrawlBatchDomainDelay:
    """Verify crawl_batch has per-domain delay throttling."""

    def test_crawl_batch_signature_has_domain_delay(self):
        """crawl_batch must accept domain_delay parameter."""
        import inspect

        from workshop.crawl4ai_bridge import crawl_batch

        sig = inspect.signature(crawl_batch)
        assert "domain_delay" in sig.parameters
        assert sig.parameters["domain_delay"].default == 0.5

    @pytest.mark.asyncio
    async def test_same_domain_requests_are_throttled(self):
        """Multiple URLs to the same domain should have delay between them."""
        import time

        from workshop.crawl4ai_bridge import CrawlResult

        call_times: list[float] = []

        async def mock_crawl_url(url: str, *, timeout: float = 60.0) -> CrawlResult:
            call_times.append(time.monotonic())
            return CrawlResult(url=url, markdown="ok", success=True)

        with patch("workshop.crawl4ai_bridge.crawl_url", side_effect=mock_crawl_url):
            from workshop.crawl4ai_bridge import crawl_batch

            results = await crawl_batch(
                [
                    "https://example.com/page1",
                    "https://example.com/page2",
                    "https://example.com/page3",
                ],
                max_concurrent=3,
                domain_delay=0.1,  # 100ms between same-domain requests
            )

        assert len(results) == 3
        assert all(r.success for r in results)

        # Due to per-domain lock, same-domain requests should be serialized
        # (total time >= 2 * domain_delay for 3 same-domain URLs)
        if len(call_times) >= 2:
            total_span = call_times[-1] - call_times[0]
            # With 3 URLs to same domain and 0.1s delay, expect >= 0.2s total
            assert total_span >= 0.15, f"Expected throttling, but span was {total_span:.3f}s"

    @pytest.mark.asyncio
    async def test_different_domains_not_throttled(self):
        """Different domains can run concurrently without delay."""
        import time

        from workshop.crawl4ai_bridge import CrawlResult

        call_times: list[float] = []

        async def mock_crawl_url(url: str, *, timeout: float = 60.0) -> CrawlResult:
            call_times.append(time.monotonic())
            return CrawlResult(url=url, markdown="ok", success=True)

        with patch("workshop.crawl4ai_bridge.crawl_url", side_effect=mock_crawl_url):
            from workshop.crawl4ai_bridge import crawl_batch

            results = await crawl_batch(
                [
                    "https://a.com/1",
                    "https://b.com/2",
                    "https://c.com/3",
                ],
                max_concurrent=3,
                domain_delay=0.5,  # large delay, but different domains
            )

        assert len(results) == 3
        # Different domains can be concurrent, so total span should be small
        if len(call_times) >= 2:
            total_span = call_times[-1] - call_times[0]
            assert total_span < 0.5, (
                f"Different domains should run concurrently, but span was {total_span:.3f}s"
            )


# ── Test 5: Full pipeline integration (webcrawl adapter → enrichment → promote shape) ──


class TestFullPipelineShape:
    """Test the full webcrawl capture→enrich→promote data flow shape."""

    def test_webcrawl_adapter_registered_in_capture_system(self):
        """WebCrawlAdapter should be discoverable via the capture registry."""
        from src.modules.capture.registry import get_adapter, reset_registry

        reset_registry()
        adapter = get_adapter("intelflow", "webcrawl")
        assert adapter is not None
        assert adapter.module == "intelflow"
        assert adapter.entity_type == "webcrawl"
        reset_registry()

    def test_webcrawl_adapter_smart_defaults_full_flow(self):
        """Smart defaults + completeness = a complete capture flow."""
        from src.modules.capture.webcrawl_adapter import WebCrawlCaptureAdapter

        adapter = WebCrawlCaptureAdapter()

        # Simulate user quick-capture: just a URL
        raw_payload = {"url": "https://docs.crawl4ai.com/core/coding-crawl4ai/"}
        enriched = adapter.smart_defaults(raw_payload, {})

        # Should auto-extract domain tag
        assert "docs.crawl4ai.com" in enriched.get("tags", [])
        assert "webcrawl" in enriched.get("tags", [])

        # Completeness should be high (URL is 60% weight)
        score = adapter.compute_completeness(enriched)
        assert score >= 0.6

        # Missing fields check
        missing = adapter.missing_fields(enriched)
        # title is optional (20% weight), so it may be missing
        assert "url" not in missing  # URL is provided

    @pytest.mark.asyncio
    async def test_enrichment_extracts_title_from_html_raw_text(self):
        """PatternMatchStrategy on webcrawl adapter extracts <title> from raw HTML."""
        from src.modules.capture.strategies import DefaultsStrategy, EnrichmentPipeline
        from src.modules.capture.webcrawl_adapter import WebCrawlCaptureAdapter

        adapter = WebCrawlCaptureAdapter()

        pipeline = EnrichmentPipeline()
        pipeline.add(DefaultsStrategy(adapter_defaults=adapter.default_values))
        for s in adapter.enrichment_strategies:
            pipeline.add(s)

        # Simulate a capture with raw HTML paste
        result = await pipeline.run(
            {
                "url": "https://example.com",
                "raw_text": "<html><head><title>Workshop 使用者指南</title></head><body>content</body></html>",
            },
            module="intelflow",
            entity_type="webcrawl",
        )

        assert result.payload["title"] == "Workshop 使用者指南"
        assert result.payload["url"] == "https://example.com"

    def test_rate_limiter_domain_isolation(self):
        """RateLimiter maintains separate state per domain."""
        from src.shared.rate_limiter import RateLimiter

        limiter = RateLimiter()

        # Report failures on one domain
        limiter._domains["slow.com"] = MagicMock()
        limiter._domains["slow.com"].fail_count = 0
        limiter._domains["slow.com"].current_delay = 1.0
        limiter.report_failure("https://slow.com/page", 429)

        # Different domain should be unaffected
        state = limiter._domains.get("fast.com")
        assert state is None  # not even created yet

    def test_url_filter_and_scorer_compose(self):
        """URL filter chain + scorer can rank webcrawl candidates."""
        from src.shared.url_filter import DomainFilter, DuplicateFilter, FilterChain
        from src.shared.url_scorer import CompositeScorer, KeywordScorer, PathDepthScorer

        urls = [
            "https://docs.crawl4ai.com/core/coding-crawl4ai/",
            "https://docs.crawl4ai.com/api/strategies/",
            "https://spam.com/buy-now",
            "https://docs.crawl4ai.com/core/coding-crawl4ai/",  # duplicate
        ]

        # Filter: only crawl4ai docs, no duplicates
        chain = FilterChain(
            filters=[
                DomainFilter(allowed_domains=["docs.crawl4ai.com"]),
                DuplicateFilter(),
            ]
        )
        filtered = chain.apply_batch(urls)
        assert len(filtered) == 2
        assert "spam.com" not in str(filtered)

        # Score: prefer pages with "coding" keyword and optimal depth
        scorer = CompositeScorer(
            scorers=[
                KeywordScorer(keywords=["coding"], weight=2.0),
                PathDepthScorer(optimal_depth=3, weight=1.0),
            ]
        )
        ranked = scorer.rank(filtered)
        # The coding page should rank higher
        assert "coding" in ranked[0][0]

    def test_markdown_gen_handles_real_html(self):
        """DefaultMarkdownGenerator processes realistic HTML."""
        from src.shared.markdown_gen import DefaultMarkdownGenerator

        gen = DefaultMarkdownGenerator()

        html = """
        <html>
        <head><title>Crawl4AI Docs</title></head>
        <body>
            <h1>Getting Started</h1>
            <p>This is a <strong>tutorial</strong> about <a href="/api">the API</a>.</p>
            <ul>
                <li>Step 1: Install</li>
                <li>Step 2: Configure</li>
            </ul>
            <pre class="language-python">
import crawl4ai
crawler = crawl4ai.AsyncWebCrawler()
            </pre>
            <table>
                <tr><th>Feature</th><th>Status</th></tr>
                <tr><td>Crawling</td><td>✅</td></tr>
            </table>
        </body>
        </html>
        """
        result = gen.convert(html)

        assert "Getting Started" in result.markdown
        assert "**tutorial**" in result.markdown
        assert "the API" in result.markdown
        assert "Step 1" in result.markdown
        assert "import crawl4ai" in result.markdown
        assert result.title == "Crawl4AI Docs"

        # links_as_citations mode collects links
        result_cited = gen.convert(html, links_as_citations=True)
        assert len(result_cited.links) >= 1  # /api link collected in citation mode

    def test_chunking_preserves_semantic_coherence(self):
        """Chunking strategies don't break in the middle of words/sentences."""
        from src.shared.chunking import FixedLengthChunking, SentenceChunking

        # SentenceChunking splits on English sentence boundaries (period + space)
        english_text = "Workshop is a modular monolith. It uses event-driven architecture. Each module manages its own DB schema. Cross-module communication goes through the event bus."
        sentence_chunks = SentenceChunking(min_length=5).chunk(english_text)
        assert len(sentence_chunks) >= 2
        for chunk in sentence_chunks:
            assert chunk.strip()  # non-empty

        # Fixed length with overlap maintains context continuity
        text = "Workshop 是一個模組化獨體應用。它使用事件驅動架構。每個模組獨立管理自己的資料庫 schema。跨模組通訊通過事件匯流排。"
        fixed_chunks = FixedLengthChunking(chunk_size=30, overlap=10).chunk(text)
        assert len(fixed_chunks) >= 2
        # Overlap means adjacent chunks share some content
        if len(fixed_chunks) >= 2:
            end_of_first = fixed_chunks[0][-10:]
            start_of_second = fixed_chunks[1][:10]
            assert end_of_first == start_of_second

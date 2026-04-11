"""Comprehensive tests for the Memvault Seven Defenses.

Tests cover:
- Phase A1: Noise Filter (check_noise, filter_results, quarantine tag)
- Phase A2: Scoring Pipeline (7 stages, metadata tracking)
- Phase B1: RRF Hybrid Retrieval (fusion, CJK detection)
- Phase B2: Adaptive Retrieval (should_search, skip_adaptive)
- Phase C2: Cross-Encoder Reranking (Defense ⑥)
- Integration: Full pipeline flow
"""

from datetime import UTC, datetime, timedelta

import pytest
from src.modules.memvault.noise_filter import (
    QUARANTINE_TAG,
    check_noise,
    filter_results,
)
from src.modules.memvault.query_runtime import (
    build_injection_payload,
    choose_thinking_mode,
)
from src.modules.memvault.schemas import (
    EnhancedSearchResult,
    MemoryCard,
    MemoryEvidenceRef,
    MemoryBlockCreate,
    MemoryBlockResponse,
    MemoryQueryResponse,
    MemoryQueryStrategy,
    SearchMetadata,
    SemanticSearchResult,
)
from src.modules.memvault.scopes import Scope, parse_scopes, scopes_to_filters
from src.modules.memvault.scoring_pipeline import (
    ScoringConfig,
    ScoringPipeline,
)
from src.modules.memvault.services import (
    MemoryBlockService,
    should_search,
)
from src.shared.scoring_stages import cosine_similarity

# ======================== Helpers ========================


def _make_block_response(
    content: str = "some valid content here",
    confidence: float = 0.8,
    block_id: str = "block1",
    created_at: datetime | None = None,
) -> MemoryBlockResponse:
    return MemoryBlockResponse(
        id=block_id,
        space_id="default",
        created_by="user1",
        created_at=created_at or datetime.now(UTC),
        updated_at=datetime.now(UTC),
        content=content,
        block_type="knowledge",
        tags=[],
        source_session=None,
        confidence=confidence,
    )


def _make_search_result(
    content: str = "some valid content here",
    score: float = 0.8,
    confidence: float = 0.8,
    block_id: str = "block1",
    created_at: datetime | None = None,
) -> SemanticSearchResult:
    return SemanticSearchResult(
        block=_make_block_response(content, confidence, block_id, created_at),
        score=score,
    )


def _make_scored_dict(
    content: str = "some valid content here",
    score: float = 0.8,
    confidence: float = 0.8,
    created_at: datetime | None = None,
    embedding: list[float] | None = None,
) -> dict:
    block = _make_block_response(content, confidence, created_at=created_at)
    return {
        "block": block,
        "score": score,
        "content": content,
        "created_at": created_at or datetime.now(UTC),
        "confidence": confidence,
        "embedding": embedding,
    }


# ======================== Phase A1: Noise Filter Tests ========================


class TestNoiseFilter:
    def test_greeting_detected(self):
        verdict = check_noise("hello")
        assert verdict.is_noise
        assert verdict.reason == "too_short"  # < 10 chars

    def test_greeting_long_detected(self):
        verdict = check_noise("hello!!!!!!!!")
        assert verdict.is_noise
        assert verdict.reason == "greeting"

    def test_greeting_with_question_not_noise(self):
        verdict = check_noise("hello, how are you doing today?")
        assert not verdict.is_noise

    def test_agent_refusal_detected(self):
        verdict = check_noise("I cannot help with that specific request right now.")
        assert verdict.is_noise
        assert verdict.reason == "agent_refusal"

    def test_short_content(self):
        verdict = check_noise("hi")
        assert verdict.is_noise
        assert verdict.reason == "too_short"

    def test_heartbeat_detected(self):
        verdict = check_noise("ping")
        assert verdict.is_noise
        assert verdict.reason == "heartbeat"

    def test_repetitive_content(self):
        verdict = check_noise("aaaaaaaaaaaaaaaaaaaaaa")
        assert verdict.is_noise
        assert verdict.reason == "repetitive"

    def test_normal_content_passes(self):
        verdict = check_noise("The user prefers Python 3.12 with type hints for all projects.")
        assert not verdict.is_noise

    def test_cjk_greeting(self):
        verdict = check_noise("你好")
        assert verdict.is_noise
        assert verdict.reason == "too_short"

    def test_cjk_greeting_long(self):
        verdict = check_noise("你好\uff01\uff01\uff01\uff01\uff01\uff01\uff01\uff01")
        assert verdict.is_noise
        assert verdict.reason == "greeting"

    def test_filter_results_removes_noise(self):
        results = [
            _make_search_result("This is a meaningful memory about Python."),
            _make_search_result("hello", block_id="block2"),
            _make_search_result("Important architecture decision.", block_id="block3"),
        ]
        clean, filtered = filter_results(results)
        assert len(clean) == 2
        assert filtered == 1

    def test_quarantine_tag_added(self):
        """Test that before_create adds quarantine tag for noisy content."""
        svc = MemoryBlockService()
        data = MemoryBlockCreate(content="hi", block_type="general", tags=["test"])
        result = svc.before_create(data)
        assert QUARANTINE_TAG in result["tags"]

    def test_no_quarantine_for_normal_content(self):
        svc = MemoryBlockService()
        data = MemoryBlockCreate(
            content="The user loves functional programming patterns.",
            block_type="knowledge",
            tags=["test"],
        )
        result = svc.before_create(data)
        assert QUARANTINE_TAG not in result["tags"]

    def test_memory_keyword_not_noise(self):
        verdict = check_noise("記得之前說過要用 FastAPI")
        assert not verdict.is_noise

    def test_agent_refusal_cjk(self):
        verdict = check_noise("我無法處理這個請求因為我是一個 AI 語言模型")
        assert verdict.is_noise
        assert verdict.reason == "agent_refusal"


# ======================== Phase A2: Scoring Pipeline Tests ========================


@pytest.mark.asyncio
class TestScoringPipeline:
    async def test_recency_boost_recent_higher(self):
        now = datetime.now(UTC)
        recent = _make_scored_dict(
            content="Recent knowledge about Python",
            score=0.7,
            created_at=now - timedelta(hours=1),
        )
        old = _make_scored_dict(
            content="Old knowledge about Python",
            score=0.7,
            created_at=now - timedelta(days=60),
        )
        pipeline = ScoringPipeline(
            ScoringConfig(
                stages_enabled={
                    "recency": True,
                    "importance": False,
                    "length_norm": False,
                    "time_decay": False,
                    "min_score": False,
                    "noise_filter": False,
                    "mmr": False,
                }
            )
        )
        results, meta = await pipeline.apply([recent, old])
        assert results[0]["score"] > results[1]["score"]
        assert "recency" in meta.stages_applied

    async def test_importance_weight_high_confidence(self):
        high_conf = _make_scored_dict(
            content="High confidence knowledge item",
            score=0.7,
            confidence=1.0,
        )
        low_conf = _make_scored_dict(
            content="Low confidence knowledge item",
            score=0.7,
            confidence=0.1,
        )
        pipeline = ScoringPipeline(
            ScoringConfig(
                stages_enabled={
                    "recency": False,
                    "importance": True,
                    "length_norm": False,
                    "time_decay": False,
                    "min_score": False,
                    "noise_filter": False,
                    "mmr": False,
                }
            )
        )
        results, _ = await pipeline.apply([high_conf, low_conf])
        assert results[0]["score"] > results[1]["score"]

    async def test_length_normalization(self):
        # Near-anchor content (400 chars) vs very long (5000 chars)
        optimal = _make_scored_dict(content="A" * 400, score=0.7)
        long = _make_scored_dict(content="L" * 5000, score=0.7)
        pipeline = ScoringPipeline(
            ScoringConfig(
                stages_enabled={
                    "recency": False,
                    "importance": False,
                    "length_norm": True,
                    "time_decay": False,
                    "min_score": False,
                    "noise_filter": False,
                    "mmr": False,
                }
            )
        )
        results, _ = await pipeline.apply([optimal, long])
        # Near-anchor content should score higher than very long content
        optimal_score = next(r["score"] for r in results if len(r["content"]) == 400)
        long_score = next(r["score"] for r in results if len(r["content"]) == 5000)
        assert optimal_score > long_score

    async def test_min_score_filter(self):
        good = _make_scored_dict(content="Good quality memory result", score=0.5)
        bad = _make_scored_dict(content="Bad quality memory result", score=0.10)
        pipeline = ScoringPipeline(
            ScoringConfig(
                stages_enabled={
                    "recency": False,
                    "importance": False,
                    "length_norm": False,
                    "time_decay": False,
                    "min_score": True,
                    "noise_filter": False,
                    "mmr": False,
                }
            )
        )
        results, _meta = await pipeline.apply([good, bad])
        assert len(results) == 1
        assert results[0]["score"] >= 0.20

    async def test_mmr_deduplication(self):
        emb1 = [1.0] * 768
        emb2 = [1.0] * 768  # identical = similarity 1.0
        emb3 = [0.0] * 768

        r1 = _make_scored_dict(
            content="First memory about Python programming",
            score=0.8,
            embedding=emb1,
        )
        r2 = _make_scored_dict(
            content="Second memory about Python programming",
            score=0.7,
            embedding=emb2,
        )
        r3 = _make_scored_dict(
            content="Third memory about something different",
            score=0.6,
            embedding=emb3,
        )
        pipeline = ScoringPipeline(
            ScoringConfig(
                stages_enabled={
                    "recency": False,
                    "importance": False,
                    "trust_boost": False,
                    "feedback_boost": False,
                    "length_norm": False,
                    "time_decay": False,
                    "semantic_boost": False,
                    "min_score": False,
                    "noise_filter": False,
                    "mmr": True,
                }
            )
        )
        results, _meta = await pipeline.apply([r1, r2, r3], query_embedding=emb1)
        # r2 should have reduced score due to similarity with r1
        scores = [r["score"] for r in results]
        assert scores[0] == 0.8  # r1 unchanged
        # r2 score should be reduced (0.7 * 0.5 = 0.35)
        assert any(s < 0.7 for s in scores if s != 0.8 and s != 0.6)

    async def test_stage_bypass_config(self):
        pipeline = ScoringPipeline(
            ScoringConfig(
                stages_enabled={
                    "recency": False,
                    "importance": False,
                    "trust_boost": False,
                    "feedback_boost": False,
                    "length_norm": False,
                    "time_decay": False,
                    "semantic_boost": False,
                    "min_score": False,
                    "noise_filter": False,
                    "mmr": False,
                }
            )
        )
        _results, meta = await pipeline.apply(
            [_make_scored_dict(content="Test memory content here", score=0.5)]
        )
        assert len(meta.stages_applied) == 0
        assert len(meta.stages_skipped) == 10

    async def test_scoring_metadata_tracking(self):
        pipeline = ScoringPipeline()
        items = [
            _make_scored_dict(content="Valid memory about architecture", score=0.7),
            _make_scored_dict(content="ping", score=0.3),
        ]
        _results, meta = await pipeline.apply(items)
        assert meta.input_count == 2
        assert meta.output_count <= 2

    async def test_empty_input_handling(self):
        pipeline = ScoringPipeline()
        results, meta = await pipeline.apply([])
        assert results == []
        assert meta.input_count == 0
        assert meta.output_count == 0


# ======================== Phase B1: RRF Fusion Tests ========================


class TestRRFFusion:
    @pytest.mark.asyncio
    async def test_rrf_basic_fusion(self):
        svc = MemoryBlockService()
        v_results = [
            _make_search_result("Memory about Python", score=0.9, block_id="b1"),
            _make_search_result("Memory about FastAPI", score=0.8, block_id="b2"),
        ]
        k_results = [
            _make_search_result("Memory about Python", score=0.5, block_id="b1"),
            _make_search_result("Memory about SQLAlchemy", score=0.4, block_id="b3"),
        ]
        fused = await svc._rrf_fuse(v_results, k_results)
        # b1 appears in both → highest fused score
        assert fused[0].block.id == "b1"
        assert len(fused) == 3  # b1, b2, b3

    @pytest.mark.asyncio
    async def test_rrf_keyword_boost(self):
        svc = MemoryBlockService()
        v_results = [
            _make_search_result("Memory A", score=0.9, block_id="b1"),
        ]
        k_results = [
            _make_search_result("Memory A", score=0.5, block_id="b1"),
        ]
        fused_with_boost = await svc._rrf_fuse(v_results, k_results, keyword_boost=0.5)
        fused_no_boost = await svc._rrf_fuse(v_results, k_results, keyword_boost=0.0)
        # With boost, keyword contribution is higher
        assert fused_with_boost[0].score >= fused_no_boost[0].score

    @pytest.mark.asyncio
    async def test_rrf_disjoint_results(self):
        svc = MemoryBlockService()
        v_results = [
            _make_search_result("Vector only result", score=0.9, block_id="b1"),
        ]
        k_results = [
            _make_search_result("Keyword only result", score=0.5, block_id="b2"),
        ]
        fused = await svc._rrf_fuse(v_results, k_results)
        assert len(fused) == 2
        ids = {r.block.id for r in fused}
        assert ids == {"b1", "b2"}

    @pytest.mark.asyncio
    async def test_rrf_empty_keyword_results(self):
        svc = MemoryBlockService()
        v_results = [
            _make_search_result("Vector result", score=0.9, block_id="b1"),
        ]
        fused = await svc._rrf_fuse(v_results, [])
        assert len(fused) == 1
        assert fused[0].block.id == "b1"

    def test_cjk_detection(self):
        from src.modules.memvault.services import _CJK_RANGES

        assert _CJK_RANGES.search("記得") is not None
        assert _CJK_RANGES.search("hello") is None
        assert _CJK_RANGES.search("mixed 中文 text") is not None


# ======================== Phase B2: Adaptive Retrieval Tests ========================


class TestAdaptiveRetrieval:
    def test_short_cjk_skipped(self):
        do, reason = should_search("你")
        assert do is False
        assert reason == "cjk_too_short"

    def test_short_english_skipped(self):
        do, reason = should_search("hi there")
        assert do is False
        assert reason == "too_short"

    def test_greeting_skipped(self):
        do, reason = should_search("hello!!!!!!!!")
        assert do is False
        assert reason == "greeting"

    def test_memory_keyword_forces_search(self):
        do, reason = should_search("記得上次說的那個方案")
        assert do is True
        assert reason == "memory_keyword"

    def test_memory_keyword_english(self):
        do, reason = should_search("Do you remember what we discussed earlier?")
        assert do is True
        assert reason == "memory_keyword"

    def test_normal_query_passes(self):
        do, reason = should_search("What are the best practices for error handling?")
        assert do is True
        assert reason == "default"


class TestFastSlowQueryRuntime:
    def test_choose_thinking_mode_auto_agent_prefers_fast(self):
        assert choose_thinking_mode("build", "auto", "standard", "agent") == "fast"

    def test_choose_thinking_mode_ui_prefers_slow(self):
        assert choose_thinking_mode("build", "auto", "standard", "ui") == "slow"

    def test_choose_thinking_mode_reflect_prefers_slow(self):
        assert choose_thinking_mode("reflect", "auto", "standard", "human") == "slow"

    def test_build_injection_payload_uses_cards(self):
        response = MemoryQueryResponse(
            query="python preferences",
            strategy=MemoryQueryStrategy(
                task_mode="build",
                thinking_mode_requested="auto",
                thinking_mode_used="fast",
                load_budget="light",
                consumer="agent",
            ),
            cards=[
                MemoryCard(
                    id="fast-1",
                    title="偏好 / architecture",
                    summary="偏好漸進式重構而非全面重寫",
                    why_relevant="命中既有工作原則",
                    use_now="延續這個原則處理目前變更。",
                    layer="fast",
                    source_type="attitude",
                    confidence=0.9,
                    evidence_refs=[
                        MemoryEvidenceRef(
                            kind="attitude",
                            ref_id="att-1",
                            title="architecture",
                            snippet="偏好漸進式重構而非全面重寫",
                        )
                    ],
                )
            ],
            cascade_cards=[],
            highlights=["延續這個原則處理目前變更。"],
            metadata={"backend": "mock"},
        )
        payload = build_injection_payload(response)
        assert "Memvault Fast Memory" in payload.system_prompt_memory
        assert "偏好漸進式重構而非全面重寫" in payload.system_prompt_memory
        assert payload.decision_bias == ["偏好漸進式重構而非全面重寫"]


# ======================== Integration Tests ========================


class TestIntegration:
    @pytest.mark.asyncio
    async def test_search_endpoint_with_adaptive_skip(self):
        """Test that adaptive retrieval skips short queries."""

        # Verify should_search properly skips
        do, _reason = should_search("hi")
        assert do is False

    @pytest.mark.asyncio
    async def test_search_endpoint_with_metadata(self):
        """Test that metadata is properly constructed."""
        meta = SearchMetadata(
            vector_used=True,
            keyword_used=True,
            scoring_applied=True,
            stages_applied=["recency", "importance"],
            stages_skipped=["mmr"],
            noise_filtered=2,
            input_count=10,
            output_count=8,
        )
        result = EnhancedSearchResult(results=[], metadata=meta)
        assert result.metadata is not None
        assert result.metadata.vector_used is True
        assert result.metadata.noise_filtered == 2

    @pytest.mark.asyncio
    async def test_full_pipeline_flow(self):
        """Test end-to-end: noise filter → scoring → RRF."""
        svc = MemoryBlockService()

        # Test noise filter in before_create
        noisy_data = MemoryBlockCreate(content="test", block_type="general")
        result = svc.before_create(noisy_data)
        assert QUARANTINE_TAG in result["tags"]

        # Test scoring pipeline
        pipeline = ScoringPipeline()
        items = [
            _make_scored_dict(
                content="Important architecture decision about microservices",
                score=0.8,
                confidence=0.9,
                created_at=datetime.now(UTC) - timedelta(hours=1),
            ),
            _make_scored_dict(
                content="hello world",  # noise — too short for content but >10 chars
                score=0.3,
                confidence=0.1,
                created_at=datetime.now(UTC) - timedelta(days=30),
            ),
        ]
        scored, meta = await pipeline.apply(items)
        assert meta.input_count == 2
        # The high-quality item should remain
        assert any(d["score"] > 0.2 for d in scored)

        # Test RRF fusion
        v = [_make_search_result("Python patterns", score=0.9, block_id="p1")]
        k = [_make_search_result("Python patterns", score=0.5, block_id="p1")]
        fused = await svc._rrf_fuse(v, k)
        assert fused[0].block.id == "p1"

    def test_cosine_similarity(self):
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(1.0)

        c = [0.0, 1.0, 0.0]
        assert cosine_similarity(a, c) == pytest.approx(0.0)

        assert cosine_similarity([], []) == 0.0
        assert cosine_similarity([0, 0, 0], [1, 1, 1]) == 0.0


# ======================== Defense ⑤: Task-Aware Embedding Tests ========================


class TestTaskAwareEmbedding:
    """Tests for Defense ⑤: Task-Aware Embedding."""

    @pytest.mark.asyncio
    async def test_search_query_prefix(self):
        """Verify prefix is correctly prepended for search queries."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [[0.1] * 768]}

        with patch("src.shared.embedding._get_client") as mock_client:
            mock_client.return_value.post = AsyncMock(return_value=mock_response)
            from src.shared.embedding import get_embedding

            result = await get_embedding("test query", task_type="search_query")
            assert result is not None
            assert len(result) == 768
            call_args = mock_client.return_value.post.call_args
            sent_input = call_args[1]["json"]["input"]
            assert sent_input == "search_query: test query"

    @pytest.mark.asyncio
    async def test_search_document_prefix(self):
        """Verify prefix is correctly prepended for document storage."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [[0.2] * 768]}

        with patch("src.shared.embedding._get_client") as mock_client:
            mock_client.return_value.post = AsyncMock(return_value=mock_response)
            from src.shared.embedding import get_embedding

            result = await get_embedding("my document content", task_type="search_document")
            assert result is not None
            call_args = mock_client.return_value.post.call_args
            sent_input = call_args[1]["json"]["input"]
            assert sent_input == "search_document: my document content"

    @pytest.mark.asyncio
    async def test_no_prefix_backward_compat(self):
        """Verify None task_type produces no prefix (backward compat)."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [[0.3] * 768]}

        with patch("src.shared.embedding._get_client") as mock_client:
            mock_client.return_value.post = AsyncMock(return_value=mock_response)
            from src.shared.embedding import get_embedding

            result = await get_embedding("plain text")
            assert result is not None
            call_args = mock_client.return_value.post.call_args
            sent_input = call_args[1]["json"]["input"]
            assert sent_input == "plain text"

    @pytest.mark.asyncio
    async def test_batch_embedding_with_prefix(self):
        """Verify batch embedding works with task_type."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "embeddings": [[0.1] * 768, [0.2] * 768],
        }

        with patch("src.shared.embedding._get_client") as mock_client:
            mock_client.return_value.post = AsyncMock(return_value=mock_response)
            from src.shared.embedding import get_embeddings_batch

            results = await get_embeddings_batch(
                ["doc one", "doc two"],
                task_type="search_document",
            )
            assert len(results) == 2
            assert all(r is not None and len(r) == 768 for r in results)
            call_args = mock_client.return_value.post.call_args
            sent_input = call_args[1]["json"]["input"]
            assert sent_input == [
                "search_document: doc one",
                "search_document: doc two",
            ]


# ======================== Phase C2: Reranker Tests ========================


class TestReranker:
    """Tests for Defense ⑥: Cross-Encoder Reranking."""

    def test_circuit_breaker_opens_after_threshold(self):
        from src.modules.memvault.reranker import CircuitBreaker

        cb = CircuitBreaker(threshold=3, recovery=600)
        assert cb.is_available() is True
        cb.record_failure()
        cb.record_failure()
        assert cb.is_available() is True  # 2 < 3
        cb.record_failure()
        assert cb.is_available() is False  # 3 >= 3, open

    def test_circuit_breaker_recovers(self):
        from src.modules.memvault.reranker import CircuitBreaker

        cb = CircuitBreaker(threshold=2, recovery=0.01)  # 10ms recovery
        cb.record_failure()
        cb.record_failure()
        assert cb.is_available() is False
        # Wait for recovery
        import time

        time.sleep(0.02)
        assert cb.is_available() is True
        assert cb.failures == 0
        assert cb.open is False

    def test_circuit_breaker_success_resets(self):
        from src.modules.memvault.reranker import CircuitBreaker

        cb = CircuitBreaker(threshold=3, recovery=600)
        cb.record_failure()
        cb.record_failure()
        assert cb.failures == 2
        cb.record_success()
        assert cb.failures == 0
        assert cb.open is False

    @pytest.mark.asyncio
    async def test_rerank_blends_scores(self):
        from unittest.mock import AsyncMock, patch

        from src.modules.memvault.reranker import LocalReranker, RerankerConfig

        config = RerankerConfig(weight_original=0.4, weight_rerank=0.6, gate_enabled=False)
        reranker = LocalReranker(config)

        results = [
            {"content": "Python is great", "score": 0.8},
            {"content": "Java is okay", "score": 0.7},
        ]

        # Mock embeddings: query close to first doc, far from second
        query_emb = [1.0, 0.0, 0.0]
        doc_emb_1 = [0.9, 0.1, 0.0]  # close to query
        doc_emb_2 = [0.0, 0.0, 1.0]  # far from query

        with (
            patch(
                "src.shared.embedding.get_embedding",
                new_callable=AsyncMock,
                return_value=query_emb,
            ),
            patch(
                "src.shared.embedding.get_embeddings_batch",
                new_callable=AsyncMock,
                return_value=[doc_emb_1, doc_emb_2],
            ),
        ):
            reranked, applied, _gate = await reranker.rerank("python", results)

        assert applied is True
        # First result should have higher blended score
        assert reranked[0]["score"] > reranked[1]["score"]
        # Scores should be blended (not original)
        assert reranked[0]["score"] != 0.8
        assert reranked[1]["score"] != 0.7

    @pytest.mark.asyncio
    async def test_rerank_skips_when_disabled(self):
        from src.modules.memvault.reranker import LocalReranker, RerankerConfig

        config = RerankerConfig(enabled=False)
        reranker = LocalReranker(config)
        results = [
            {"content": "A", "score": 0.8},
            {"content": "B", "score": 0.7},
        ]
        reranked, applied, _gate = await reranker.rerank("test", results)
        assert applied is False
        assert reranked[0]["score"] == 0.8  # unchanged

    @pytest.mark.asyncio
    async def test_rerank_skips_single_result(self):
        from src.modules.memvault.reranker import LocalReranker

        reranker = LocalReranker()
        results = [{"content": "Only one", "score": 0.9}]
        reranked, applied, _gate = await reranker.rerank("test", results)
        assert applied is False
        assert len(reranked) == 1

    @pytest.mark.asyncio
    async def test_rerank_graceful_degradation(self):
        """Mock embedding failure → returns original results."""
        from unittest.mock import AsyncMock, patch

        from src.modules.memvault.reranker import LocalReranker, RerankerConfig

        reranker = LocalReranker(RerankerConfig(gate_enabled=False))
        results = [
            {"content": "A content", "score": 0.8},
            {"content": "B content", "score": 0.7},
        ]

        with patch(
            "src.shared.embedding.get_embedding",
            new_callable=AsyncMock,
            return_value=None,  # Ollama unavailable
        ):
            reranked, applied, _gate = await reranker.rerank("test query", results)

        assert applied is False
        assert reranked[0]["score"] == 0.8  # unchanged
        assert reranker._breaker.failures == 1

    @pytest.mark.asyncio
    async def test_rerank_circuit_breaker_skips_after_failures(self):
        """After threshold failures, reranker is skipped."""
        from unittest.mock import AsyncMock, patch

        from src.modules.memvault.reranker import LocalReranker, RerankerConfig

        config = RerankerConfig(failure_threshold=2, recovery_seconds=600, gate_enabled=False)
        reranker = LocalReranker(config)

        results = [
            {"content": "A content", "score": 0.8},
            {"content": "B content", "score": 0.7},
        ]

        # Simulate 2 embedding failures to open circuit breaker
        with patch(
            "src.shared.embedding.get_embedding",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await reranker.rerank("q1", results)
            await reranker.rerank("q2", results)

        assert reranker._breaker.open is True

        # Now reranker should be skipped without even calling embedding
        _reranked, applied, _gate = await reranker.rerank("q3", results)
        assert applied is False

    @pytest.mark.asyncio
    async def test_rerank_convenience_function(self):
        """Test the module-level rerank_results function."""
        from unittest.mock import AsyncMock, patch

        from src.modules.memvault.reranker import rerank_results

        results = [
            {"content": "A", "score": 0.8},
            {"content": "B", "score": 0.7},
        ]

        # With embedding failure, should return originals
        with patch(
            "src.shared.embedding.get_embedding",
            new_callable=AsyncMock,
            return_value=None,
        ):
            _reranked, applied, _gate = await rerank_results("test", results)
        assert applied is False


# ======================== Attention-Gated Reranker Tests ========================


class TestRerankerGating:
    """Tests for attention-gated computation on reranker.

    Pattern: use cheap scoring pipeline output to gate expensive cross-encoder.
    Inspired by TurboQuant+ Sparse V (ICLR 2026).
    """

    def test_gate_few_candidates(self):
        """Gate fires when <= gate_max_candidates survive scoring."""
        from src.modules.memvault.reranker import LocalReranker, RerankerConfig

        config = RerankerConfig(gate_enabled=True, gate_max_candidates=5)
        reranker = LocalReranker(config)
        results = [{"content": f"item {i}", "score": 0.8 - i * 0.1} for i in range(4)]
        gated, reason = reranker._should_gate(results)
        assert gated is True
        assert "few_candidates" in reason

    def test_gate_score_dominance(self):
        """Gate fires when top-1 has clear lead over #2."""
        from src.modules.memvault.reranker import LocalReranker, RerankerConfig

        config = RerankerConfig(
            gate_enabled=True,
            gate_min_top_score=0.45,
            gate_min_score_gap=0.15,
            gate_max_candidates=3,  # low so few_candidates doesn't fire first
        )
        reranker = LocalReranker(config)
        results = [
            {"content": "A", "score": 0.85},
            {"content": "B", "score": 0.60},
            *[{"content": f"C{i}", "score": 0.5 - i * 0.05} for i in range(8)],
        ]
        gated, reason = reranker._should_gate(results)
        assert gated is True
        assert "score_dominance" in reason

    def test_gate_tight_cluster(self):
        """Gate fires when top scores are tightly clustered."""
        from src.modules.memvault.reranker import LocalReranker, RerankerConfig

        config = RerankerConfig(
            gate_enabled=True,
            gate_min_cluster_tightness=0.05,
            gate_min_top_score=0.45,
            gate_max_candidates=3,
        )
        reranker = LocalReranker(config)
        # All scores very close: 0.79, 0.78, ..., 0.70
        results = [{"content": f"item {i}", "score": 0.79 - i * 0.01} for i in range(10)]
        gated, reason = reranker._should_gate(results)
        assert gated is True
        assert "tight_cluster" in reason

    def test_gate_does_not_fire_ambiguous(self):
        """Gate does NOT fire when scores are spread and top isn't dominant."""
        from src.modules.memvault.reranker import LocalReranker, RerankerConfig

        config = RerankerConfig(gate_enabled=True, gate_max_candidates=3)
        reranker = LocalReranker(config)
        # Wide spread, moderate gap, many candidates
        results = [{"content": f"item {i}", "score": 0.7 - i * 0.06} for i in range(10)]
        gated, _reason = reranker._should_gate(results)
        assert gated is False

    def test_gate_disabled(self):
        """Gate never fires when gate_enabled=False."""
        from src.modules.memvault.reranker import LocalReranker, RerankerConfig

        config = RerankerConfig(gate_enabled=False)
        reranker = LocalReranker(config)
        results = [{"content": "only one", "score": 0.95}]
        gated, _ = reranker._should_gate(results)
        assert gated is False

    @pytest.mark.asyncio
    async def test_gated_rerank_returns_reason(self):
        """When gated, rerank() returns gate_reason as third element."""
        from src.modules.memvault.reranker import LocalReranker, RerankerConfig

        config = RerankerConfig(gate_enabled=True, gate_max_candidates=5)
        reranker = LocalReranker(config)
        results = [
            {"content": "A", "score": 0.8},
            {"content": "B", "score": 0.7},
        ]
        _reranked, applied, gate_reason = await reranker.rerank("test", results)
        assert applied is False
        assert gate_reason is not None
        assert "few_candidates" in gate_reason

    def test_metadata_tracks_gating(self):
        """SearchMetadata reflects gating decision."""
        meta = SearchMetadata()
        meta.reranker_gated = True
        meta.reranker_gate_reason = "few_candidates(3)"
        assert meta.reranker_gated is True
        assert meta.reranker_used is False


# ======================== Defense ⑦: Multi-Scope Isolation Tests ========================


class TestMultiScope:
    """Tests for Defense ⑦: Multi-Scope Isolation."""

    def test_parse_global_scope(self):
        scopes = parse_scopes("global")
        assert len(scopes) == 1
        assert scopes[0].kind == "global"
        assert scopes[0].value is None

    def test_parse_session_scope(self):
        scopes = parse_scopes("session:abc123")
        assert len(scopes) == 1
        assert scopes[0].kind == "session"
        assert scopes[0].value == "abc123"

    def test_parse_user_scope(self):
        scopes = parse_scopes("user:user42")
        assert len(scopes) == 1
        assert scopes[0].kind == "user"
        assert scopes[0].value == "user42"

    def test_parse_type_scope(self):
        scopes = parse_scopes("type:knowledge")
        assert len(scopes) == 1
        assert scopes[0].kind == "type"
        assert scopes[0].value == "knowledge"

    def test_parse_multiple_scopes(self):
        scopes = parse_scopes("session:abc,type:knowledge")
        assert len(scopes) == 2
        assert scopes[0].kind == "session"
        assert scopes[0].value == "abc"
        assert scopes[1].kind == "type"
        assert scopes[1].value == "knowledge"

    def test_parse_invalid_scope_raises(self):
        with pytest.raises(ValueError, match="Invalid scope format"):
            parse_scopes("badformat")

    def test_parse_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown scope kind"):
            parse_scopes("unknown:value")

    def test_scope_to_filter_global_returns_none(self):
        scope = Scope(kind="global")
        assert scope.to_filter() is None

    def test_scope_to_filter_session(self):
        scope = Scope(kind="session", value="sess123")
        f = scope.to_filter()
        assert f is not None

    def test_scope_to_filter_user(self):
        scope = Scope(kind="user", value="user1")
        f = scope.to_filter()
        assert f is not None

    def test_scope_to_filter_type(self):
        scope = Scope(kind="type", value="knowledge")
        f = scope.to_filter()
        assert f is not None

    def test_scope_default_is_global(self):
        # scope=None behaves same as scope="global"
        scopes_none = parse_scopes(None)
        scopes_global = parse_scopes("global")
        assert scopes_none[0].kind == scopes_global[0].kind == "global"
        assert scopes_to_filters(scopes_none) == []
        assert scopes_to_filters(scopes_global) == []

    def test_scopes_to_filters_mixed(self):
        scopes = parse_scopes("session:s1,type:skill")
        filters = scopes_to_filters(scopes)
        assert len(filters) == 2

    def test_scope_str_representation(self):
        assert str(Scope(kind="global")) == "global"
        assert str(Scope(kind="session", value="abc")) == "session:abc"
        assert str(Scope(kind="user", value="u1")) == "user:u1"
        assert str(Scope(kind="type", value="knowledge")) == "type:knowledge"

    def test_parse_empty_string_is_global(self):
        scopes = parse_scopes("")
        assert len(scopes) == 1
        assert scopes[0].kind == "global"

    def test_parse_whitespace_handling(self):
        scopes = parse_scopes(" session:abc , type:knowledge ")
        assert len(scopes) == 2
        assert scopes[0].kind == "session"
        assert scopes[1].kind == "type"

    def test_scope_in_search_metadata(self):
        meta = SearchMetadata(scope="session:abc123")
        assert meta.scope == "session:abc123"

    def test_scope_none_in_search_metadata(self):
        meta = SearchMetadata()
        assert meta.scope is None

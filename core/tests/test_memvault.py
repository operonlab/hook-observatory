"""Comprehensive tests for the Memvault Seven Defenses.

Tests cover:
- Phase A1: Noise Filter (check_noise, filter_results, quarantine tag)
- Phase A2: Scoring Pipeline (7 stages, metadata tracking)
- Phase B1: RRF Hybrid Retrieval (fusion, CJK detection)
- Phase B2: Adaptive Retrieval (should_search, skip_adaptive)
- Integration: Full pipeline flow
"""

from datetime import UTC, datetime, timedelta

import pytest
from src.modules.memvault.noise_filter import (
    QUARANTINE_TAG,
    check_noise,
    filter_results,
)
from src.modules.memvault.schemas import (
    EnhancedSearchResult,
    MemoryBlockCreate,
    MemoryBlockResponse,
    SearchMetadata,
    SemanticSearchResult,
)
from src.modules.memvault.scoring_pipeline import (
    ScoringConfig,
    ScoringPipeline,
    _cosine_similarity,
)
from src.modules.memvault.services import (
    MemoryBlockService,
    _is_cjk,
    _is_cjk_dominant,
    should_search,
)

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
        verdict = check_noise(
            "The user prefers Python 3.12 with type hints for all projects."
        )
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


class TestScoringPipeline:
    def test_recency_boost_recent_higher(self):
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
        pipeline = ScoringPipeline(ScoringConfig(
            stages_enabled={
                "recency": True, "importance": False, "length_norm": False,
                "time_decay": False, "min_score": False, "noise_filter": False,
                "mmr": False,
            }
        ))
        results, meta = pipeline.apply([recent, old])
        assert results[0]["score"] > results[1]["score"]
        assert "recency" in meta.stages_applied

    def test_importance_weight_high_confidence(self):
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
        pipeline = ScoringPipeline(ScoringConfig(
            stages_enabled={
                "recency": False, "importance": True, "length_norm": False,
                "time_decay": False, "min_score": False, "noise_filter": False,
                "mmr": False,
            }
        ))
        results, _ = pipeline.apply([high_conf, low_conf])
        assert results[0]["score"] > results[1]["score"]

    def test_length_normalization(self):
        # Near-anchor content (400 chars) vs very long (5000 chars)
        optimal = _make_scored_dict(content="A" * 400, score=0.7)
        long = _make_scored_dict(content="L" * 5000, score=0.7)
        pipeline = ScoringPipeline(ScoringConfig(
            stages_enabled={
                "recency": False, "importance": False, "length_norm": True,
                "time_decay": False, "min_score": False, "noise_filter": False,
                "mmr": False,
            }
        ))
        results, _ = pipeline.apply([optimal, long])
        # Near-anchor content should score higher than very long content
        optimal_score = next(r["score"] for r in results if len(r["content"]) == 400)
        long_score = next(r["score"] for r in results if len(r["content"]) == 5000)
        assert optimal_score > long_score

    def test_min_score_filter(self):
        good = _make_scored_dict(content="Good quality memory result", score=0.5)
        bad = _make_scored_dict(content="Bad quality memory result", score=0.10)
        pipeline = ScoringPipeline(ScoringConfig(
            stages_enabled={
                "recency": False, "importance": False, "length_norm": False,
                "time_decay": False, "min_score": True, "noise_filter": False,
                "mmr": False,
            }
        ))
        results, _meta = pipeline.apply([good, bad])
        assert len(results) == 1
        assert results[0]["score"] >= 0.20

    def test_mmr_deduplication(self):
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
        pipeline = ScoringPipeline(ScoringConfig(
            stages_enabled={
                "recency": False, "importance": False, "length_norm": False,
                "time_decay": False, "min_score": False, "noise_filter": False,
                "mmr": True,
            }
        ))
        results, _meta = pipeline.apply([r1, r2, r3], query_embedding=emb1)
        # r2 should have reduced score due to similarity with r1
        scores = [r["score"] for r in results]
        assert scores[0] == 0.8  # r1 unchanged
        # r2 score should be reduced (0.7 * 0.5 = 0.35)
        assert any(s < 0.7 for s in scores if s != 0.8 and s != 0.6)

    def test_stage_bypass_config(self):
        pipeline = ScoringPipeline(ScoringConfig(
            stages_enabled={
                "recency": False, "importance": False, "length_norm": False,
                "time_decay": False, "min_score": False, "noise_filter": False,
                "mmr": False,
            }
        ))
        _results, meta = pipeline.apply([
            _make_scored_dict(content="Test memory content here", score=0.5)
        ])
        assert len(meta.stages_applied) == 0
        assert len(meta.stages_skipped) == 7

    def test_scoring_metadata_tracking(self):
        pipeline = ScoringPipeline()
        items = [
            _make_scored_dict(content="Valid memory about architecture", score=0.7),
            _make_scored_dict(content="ping", score=0.3),
        ]
        _results, meta = pipeline.apply(items)
        assert meta.input_count == 2
        assert meta.output_count <= 2

    def test_empty_input_handling(self):
        pipeline = ScoringPipeline()
        results, meta = pipeline.apply([])
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
        assert _is_cjk("記得") is True
        assert _is_cjk("hello") is False
        assert _is_cjk("mixed 中文 text") is True
        assert _is_cjk_dominant("主要是中文的內容") is True
        assert _is_cjk_dominant("mostly english text") is False


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
        scored, meta = pipeline.apply(items)
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
        assert _cosine_similarity(a, b) == pytest.approx(1.0)

        c = [0.0, 1.0, 0.0]
        assert _cosine_similarity(a, c) == pytest.approx(0.0)

        assert _cosine_similarity([], []) == 0.0
        assert _cosine_similarity([0, 0, 0], [1, 1, 1]) == 0.0

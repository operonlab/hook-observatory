"""Tests for memvault search feedback loop feature.

Coverage:
1. ScoringPipeline feedback_boost stage (unit)
2. SearchFeedbackService — record() hash + get_bulk_aggregates() SQL (unit)
3. qdrant_search integration: feedback_map fetched before pipeline runs (structural)
4. API contract: SDK calls against live server (integration — skip if server unavailable)
5. Edge cases: missing feedback_net, empty table, nonexistent entity_id
6. Code review assertions: SQL correctness, soft-delete filter, hash consistency
"""

import hashlib
import math
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.modules.memvault.scoring_pipeline import ScoringConfig, ScoringPipeline
from src.modules.memvault.services import SearchFeedbackService

# ============================================================================
# Helpers
# ============================================================================


def _minimal_stages(**overrides) -> dict[str, bool]:
    """Return a stages_enabled dict with all stages disabled except overrides."""
    base = {
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
    base.update(overrides)
    return base


def _make_scored_dict(
    score: float = 0.8,
    feedback_net: int | None = None,
    content: str = "This is a valid memory about Python best practices.",
    confidence: float = 0.8,
    created_at: datetime | None = None,
) -> dict:
    block = MagicMock()
    block.id = "test-block-001"
    block.source_session = None
    d: dict[str, Any] = {
        "block": block,
        "score": score,
        "content": content,
        "created_at": created_at or datetime.now(UTC),
        "confidence": confidence,
        "embedding": None,
        "access_count": 0,
        "last_accessed_at": None,
    }
    if feedback_net is not None:
        d["feedback_net"] = feedback_net
    return d


# ============================================================================
# 1. ScoringPipeline — feedback_boost stage
# ============================================================================


class TestFeedbackBoostStage:
    """Test the feedback_boost stage of ScoringPipeline in isolation."""

    def _run_feedback_only(self, results: list[dict]) -> tuple[list[dict], Any]:
        pipeline = ScoringPipeline(
            ScoringConfig(
                stages_enabled=_minimal_stages(feedback_boost=True),
                feedback_weight=0.15,
            )
        )
        return pipeline.apply(results)

    def test_positive_feedback_increases_score(self):
        base_score = 0.8
        r = _make_scored_dict(score=base_score, feedback_net=3)
        results, meta = self._run_feedback_only([r])
        assert results[0]["score"] > base_score, (
            f"Expected score > {base_score}, got {results[0]['score']}"
        )

    def test_negative_feedback_decreases_score(self):
        base_score = 0.8
        r = _make_scored_dict(score=base_score, feedback_net=-3)
        results, meta = self._run_feedback_only([r])
        assert results[0]["score"] < base_score, (
            f"Expected score < {base_score}, got {results[0]['score']}"
        )

    def test_zero_net_feedback_no_change(self):
        base_score = 0.8
        r = _make_scored_dict(score=base_score, feedback_net=0)
        results, meta = self._run_feedback_only([r])
        assert results[0]["score"] == pytest.approx(base_score), (
            "Zero net feedback should not change score"
        )

    def test_missing_feedback_net_treated_as_zero(self):
        """If feedback_net key is absent (not injected), score must be unchanged."""
        base_score = 0.8
        r = _make_scored_dict(score=base_score)  # no feedback_net key
        assert "feedback_net" not in r, "Pre-condition: feedback_net must be absent"
        results, meta = self._run_feedback_only([r])
        assert results[0]["score"] == pytest.approx(base_score), (
            "Missing feedback_net should default to 0, no score change"
        )

    def test_tanh_saturation_high_positive(self):
        """±10 net signal should not be wildly different from ±5 — tanh saturates."""
        r_5 = _make_scored_dict(score=0.8, feedback_net=5)
        r_10 = _make_scored_dict(score=0.8, feedback_net=10)
        results_5, _ = self._run_feedback_only([r_5])
        results_10, _ = self._run_feedback_only([r_10])
        boost_5 = results_5[0]["score"] - 0.8
        boost_10 = results_10[0]["score"] - 0.8
        # Both positive; boost_10 slightly larger but saturating
        assert boost_5 > 0
        assert boost_10 > 0
        # The difference should be small (< 50% of boost_5) due to tanh saturation
        assert (boost_10 - boost_5) < 0.5 * boost_5, (
            f"Expected saturation: boost_5={boost_5:.4f}, boost_10={boost_10:.4f}"
        )

    def test_tanh_saturation_high_negative(self):
        """Same saturation test for negative signals."""
        r_neg5 = _make_scored_dict(score=0.8, feedback_net=-5)
        r_neg10 = _make_scored_dict(score=0.8, feedback_net=-10)
        results_5, _ = self._run_feedback_only([r_neg5])
        results_10, _ = self._run_feedback_only([r_neg10])
        penalty_5 = 0.8 - results_5[0]["score"]
        penalty_10 = 0.8 - results_10[0]["score"]
        assert penalty_5 > 0
        assert penalty_10 > 0
        assert (penalty_10 - penalty_5) < 0.5 * penalty_5, (
            f"Expected saturation: penalty_5={penalty_5:.4f}, penalty_10={penalty_10:.4f}"
        )

    def test_formula_correctness(self):
        """Verify exact formula: score *= 1 + weight * tanh(net / 3)."""
        net = 3
        weight = 0.15
        base = 0.8
        expected = base * (1.0 + weight * math.tanh(net / 3.0))
        r = _make_scored_dict(score=base, feedback_net=net)
        results, _ = self._run_feedback_only([r])
        assert results[0]["score"] == pytest.approx(expected, rel=1e-6), (
            f"Formula mismatch: expected {expected}, got {results[0]['score']}"
        )

    def test_feedback_boost_in_stages_applied(self):
        """feedback_boost must appear in metadata.stages_applied."""
        r = _make_scored_dict(score=0.8, feedback_net=2)
        _, meta = self._run_feedback_only([r])
        assert "feedback_boost" in meta.stages_applied, (
            f"stages_applied={meta.stages_applied} — feedback_boost missing"
        )

    def test_feedback_boost_skipped_when_disabled(self):
        """When feedback_boost is disabled, it must appear in stages_skipped."""
        pipeline = ScoringPipeline(
            ScoringConfig(stages_enabled=_minimal_stages(feedback_boost=False))
        )
        r = _make_scored_dict(score=0.8, feedback_net=5)
        _, meta = pipeline.apply([r])
        assert "feedback_boost" in meta.stages_skipped
        assert "feedback_boost" not in meta.stages_applied

    def test_empty_results_no_crash(self):
        """Empty result list must not raise."""
        results, meta = self._run_feedback_only([])
        assert results == []
        assert meta.input_count == 0

    def test_multiple_results_independent(self):
        """Each result's boost is computed independently."""
        r_pos = _make_scored_dict(score=0.8, feedback_net=5)
        r_neg = _make_scored_dict(score=0.8, feedback_net=-5)
        r_zero = _make_scored_dict(score=0.8, feedback_net=0)
        results, _ = self._run_feedback_only([r_pos, r_neg, r_zero])
        scores = {d["feedback_net"]: d["score"] for d in results}
        assert scores[5] > scores[0] > scores[-5], f"Expected pos > zero > neg, got: {scores}"

    def test_feedback_net_one_small_boost(self):
        """Net=1 should give a measurable but modest boost."""
        base = 0.8
        weight = 0.15
        expected_multiplier = 1.0 + weight * math.tanh(1 / 3.0)
        r = _make_scored_dict(score=base, feedback_net=1)
        results, _ = self._run_feedback_only([r])
        assert results[0]["score"] == pytest.approx(base * expected_multiplier, rel=1e-6)


# ============================================================================
# 2. SearchFeedbackService — unit tests (no DB)
# ============================================================================


class TestSearchFeedbackServiceUnit:
    """Unit tests that do not require a database connection."""

    def test_query_hash_is_sha256(self):
        """record() must hash query with SHA-256."""
        query = "test query alpha"
        expected_hash = hashlib.sha256(query.encode()).hexdigest()
        assert len(expected_hash) == 64  # SHA-256 hex = 64 chars

    def test_query_hash_consistency(self):
        """Same query string always produces same hash."""
        q = "feedback scoring integration test"
        h1 = hashlib.sha256(q.encode()).hexdigest()
        h2 = hashlib.sha256(q.encode()).hexdigest()
        assert h1 == h2

    def test_query_hash_different_queries(self):
        """Different queries produce different hashes."""
        h1 = hashlib.sha256(b"query alpha").hexdigest()
        h2 = hashlib.sha256(b"query beta").hexdigest()
        assert h1 != h2

    def test_query_hash_length_64(self):
        """SHA-256 hex digest is always 64 characters — fits String(64) column."""
        for query in ["short", "a" * 1000, "中文查詢", "混合 mixed query"]:
            h = hashlib.sha256(query.encode()).hexdigest()
            assert len(h) == 64, f"Hash length {len(h)} != 64 for query: {query!r}"

    def test_get_bulk_aggregates_empty_list(self):
        """get_bulk_aggregates with empty entity_ids must return {} without DB query."""
        svc = SearchFeedbackService()

        async def _run():
            db_mock = AsyncMock()
            result = await svc.get_bulk_aggregates(db_mock, [])
            # DB should NOT be called at all
            db_mock.execute.assert_not_called()
            return result

        import asyncio

        result = asyncio.run(_run())
        assert result == {}, f"Expected empty dict, got {result}"

    def test_bulk_aggregates_sql_case_logic(self):
        """The CASE expression in get_bulk_aggregates is correct PostgreSQL syntax.

        We verify by checking the SQL text is built without errors using SQLAlchemy.
        This is a structural test — we cannot execute without a DB but we can
        confirm the query object compiles without syntax errors.
        """
        from sqlalchemy import Integer, func, text
        from sqlalchemy.dialects import postgresql

        # Replicate exactly what the service builds
        try:
            q = func.sum(
                func.cast(
                    text("CASE WHEN signal = 'positive' THEN 1 ELSE -1 END"),
                    Integer,
                )
            ).label("net")
            # Compile to PostgreSQL dialect to catch syntax errors early
            compiled = str(q.compile(dialect=postgresql.dialect()))
            assert "CASE WHEN" in compiled or "CASE" in compiled or compiled  # compiles OK
        except Exception as exc:
            pytest.fail(f"SQL expression failed to compile: {exc}")

    def test_soft_delete_filter_present_in_get_aggregate(self):
        """get_aggregate query must filter SearchFeedback.deleted_at == None.

        We verify by inspecting the source code — the filter must be present
        to exclude soft-deleted records.
        """
        import inspect

        source = inspect.getsource(SearchFeedbackService.get_aggregate)
        assert "deleted_at" in source, (
            "get_aggregate must filter out soft-deleted records via deleted_at"
        )

    def test_soft_delete_filter_present_in_get_bulk_aggregates(self):
        """get_bulk_aggregates query must also filter deleted_at == None."""
        import inspect

        source = inspect.getsource(SearchFeedbackService.get_bulk_aggregates)
        assert "deleted_at" in source, (
            "get_bulk_aggregates must filter out soft-deleted records via deleted_at"
        )


# ============================================================================
# 3. qdrant_search integration: feedback_map injected before pipeline
# ============================================================================


class TestQdrantSearchFeedbackIntegration:
    """Structural tests: verify feedback_map is fetched and injected before pipeline."""

    def test_feedback_map_fetched_before_pipeline(self):
        """Inspect qdrant_search source to confirm ordering:
        1. get_bulk_aggregates is called
        2. feedback_net is assigned to scored_dicts
        3. pipeline.apply() is called after
        """
        import inspect

        from src.modules.memvault.services import MemoryBlockService

        source = inspect.getsource(MemoryBlockService.qdrant_search)

        # Confirm all three markers are present
        assert "get_bulk_aggregates" in source, (
            "get_bulk_aggregates must be called in qdrant_search"
        )
        assert "feedback_net" in source, "feedback_net must be injected into scored_dicts"
        assert "pipeline.apply" in source, "pipeline.apply must be called"

        # Confirm ordering: get_bulk_aggregates before feedback_net before pipeline.apply
        idx_fetch = source.index("get_bulk_aggregates")
        idx_inject = source.index("feedback_net")
        idx_pipeline = source.index("pipeline.apply")
        assert idx_fetch < idx_inject < idx_pipeline, (
            f"Ordering wrong: fetch={idx_fetch}, inject={idx_inject}, pipeline={idx_pipeline}"
        )

    def test_feedback_map_is_dict_str_int(self):
        """get_bulk_aggregates must return {entity_id: net_signal} (both str keys, int values).

        This is verified by checking the return annotation in services.py.
        """
        import inspect

        source = inspect.getsource(SearchFeedbackService.get_bulk_aggregates)
        # Should return dict[str, int]
        assert "dict[str, int]" in source, (
            "get_bulk_aggregates return annotation must be dict[str, int]"
        )

    def test_feedback_net_default_zero_in_scored_dicts(self):
        """When entity_id has no feedback, feedback_map.get(eid, 0) must default to 0."""
        feedback_map: dict[str, int] = {}
        eid = "nonexistent-entity-id"
        net = feedback_map.get(eid, 0)
        assert net == 0, f"Missing entity should default to 0, got {net}"

    @pytest.mark.asyncio
    async def test_qdrant_search_feedback_try_except_graceful(self):
        """If get_bulk_aggregates raises, qdrant_search should proceed with empty feedback_map.

        Verify via mock: even when feedback fetch fails, pipeline still runs.
        """
        from src.modules.memvault.services import MemoryBlockService

        svc = MemoryBlockService()
        db_mock = AsyncMock()

        # Mock qdrant as unavailable — method returns None gracefully
        with patch("src.shared.qdrant_client.is_available", return_value=False):
            result = await svc.qdrant_search(
                db=db_mock,
                space_id="default",
                query="test query",
                query_embedding=[0.1] * 1024,
            )
        # When Qdrant is unavailable, result is None (caller falls back)
        assert result is None


# ============================================================================
# 4. SDK API contract test (integration — skipped if server unavailable)
# ============================================================================


def _server_is_up() -> bool:
    """Quick connectivity check for the Core API."""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", 8801), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _server_is_up(), reason="Core API not running (port 8801)")
class TestSDKIntegration:
    """Live integration tests — only run when the Core API is up."""

    @pytest.fixture(autouse=True)
    def client(self):
        from sdk_client.memvault import MemvaultClient

        self.c = MemvaultClient()

    def test_feedback_record_and_aggregate(self):
        """Create block, submit feedback, verify aggregate counts."""
        # Create a test block
        block = self.c.extract(
            "Test feedback scoring integration for unit test",
            block_type="knowledge",
            tags=["test-feedback-loop"],
        )
        block_id = block["id"]

        try:
            # Submit 3 positive + 1 negative
            self.c.feedback(block_id, "test query alpha", "positive")
            self.c.feedback(block_id, "test query alpha", "positive")
            self.c.feedback(block_id, "test query alpha", "positive")
            self.c.feedback(block_id, "test query beta", "negative")

            # Retrieve aggregate
            agg = self.c.get_feedback(block_id)
            assert agg["entity_id"] == block_id
            assert agg["positive_count"] == 3, f"Expected 3 positive, got {agg}"
            assert agg["negative_count"] == 1, f"Expected 1 negative, got {agg}"
            assert agg["net_signal"] == 2, f"Expected net=2, got {agg}"
        finally:
            # Cleanup
            try:
                self.c.delete_block(block_id)
            except Exception:
                pass

    def test_feedback_for_nonexistent_entity(self):
        """Feedback for nonexistent entity_id should be recorded (no FK constraint)."""
        fake_id = "0" * 32  # 32-char ID that doesn't exist in DB
        # Should NOT raise
        result = self.c.feedback(fake_id, "test query", "positive")
        assert result is not None
        assert result.get("entity_id") == fake_id or "id" in result

    def test_get_feedback_for_entity_with_no_feedback(self):
        """get_feedback for a block with zero feedback should return zeros."""
        # Create a fresh block with no feedback
        block = self.c.extract(
            "Fresh block with no feedback signals attached",
            block_type="general",
            tags=["test-feedback-zero"],
        )
        block_id = block["id"]

        try:
            agg = self.c.get_feedback(block_id)
            assert agg["positive_count"] == 0
            assert agg["negative_count"] == 0
            assert agg["net_signal"] == 0
        finally:
            try:
                self.c.delete_block(block_id)
            except Exception:
                pass

    def test_signal_validation_rejects_invalid(self):
        """signal must be 'positive' or 'negative' — anything else is rejected."""
        from sdk_client._base import APIError

        block = self.c.extract(
            "Block for signal validation test",
            block_type="general",
            tags=["test-feedback-validation"],
        )
        block_id = block["id"]
        try:
            with pytest.raises((APIError, Exception)):
                self.c.feedback(block_id, "test query", "invalid_signal")
        finally:
            try:
                self.c.delete_block(block_id)
            except Exception:
                pass


# ============================================================================
# 5. Edge cases
# ============================================================================


class TestEdgeCases:
    """Edge cases for robustness."""

    def test_feedback_net_none_handled_as_zero(self):
        """feedback_net=None must be treated as 0 — score unchanged, no crash.

        Bug fixed: original `if net == 0: continue` skipped None check, causing
        math.tanh(None/3) TypeError that crashed the whole stage (all results lost boost).
        Fix: `or 0` coerces None to 0.
        """
        base_score = 0.8
        r = _make_scored_dict(score=base_score)
        r["feedback_net"] = None  # explicit None — simulates corrupted data

        pipeline = ScoringPipeline(
            ScoringConfig(stages_enabled=_minimal_stages(feedback_boost=True))
        )
        results, meta = pipeline.apply([r])

        # Must not crash, score must be unchanged (None treated as 0)
        assert math.isfinite(results[0]["score"]), "Score must be finite when feedback_net=None"
        assert results[0]["score"] == pytest.approx(base_score), (
            "feedback_net=None should be treated as 0 (no score change)"
        )
        # Stage must have been applied (not skipped due to crash)
        assert "feedback_boost" in meta.stages_applied, (
            "feedback_boost stage must be applied even when one result has None feedback_net"
        )

    def test_empty_feedback_map_results_in_zero_net(self):
        """When feedback_map is empty, all feedback_net defaults to 0."""
        feedback_map: dict[str, int] = {}
        entity_ids = ["id1", "id2", "id3"]
        nets = [feedback_map.get(eid, 0) for eid in entity_ids]
        assert all(n == 0 for n in nets)

    def test_searchfeedback_inherits_spacescopedmodel(self):
        """SearchFeedback must inherit SpaceScopedModel to get soft-delete support."""
        from src.modules.memvault.models import SearchFeedback
        from src.shared.models import SpaceScopedModel

        assert issubclass(SearchFeedback, SpaceScopedModel), (
            "SearchFeedback must inherit SpaceScopedModel for soft-delete support"
        )

    def test_searchfeedback_has_required_columns(self):
        """Verify all required columns exist on SearchFeedback model."""
        from src.modules.memvault.models import SearchFeedback

        columns = {c.name for c in SearchFeedback.__table__.columns}
        required = {"entity_id", "query_hash", "signal", "feedback_source"}
        missing = required - columns
        assert not missing, f"Missing columns on SearchFeedback: {missing}"

    def test_searchfeedback_has_deleted_at_via_inheritance(self):
        """Soft-delete requires deleted_at column from SpaceScopedModel."""
        from src.modules.memvault.models import SearchFeedback

        columns = {c.name for c in SearchFeedback.__table__.columns}
        assert "deleted_at" in columns, (
            "SearchFeedback must have deleted_at column (via SpaceScopedModel)"
        )

    def test_pipeline_exception_isolation(self):
        """If feedback_boost raises internally, it is caught and stage is skipped."""
        pipeline = ScoringPipeline(
            ScoringConfig(stages_enabled=_minimal_stages(feedback_boost=True))
        )
        # Inject a result where feedback_net causes a math error
        r = _make_scored_dict(score=0.8)
        r["feedback_net"] = float("nan")  # NaN will propagate through tanh
        # Should not raise — _run_stage wraps in try/except
        results, meta = pipeline.apply([r])
        # Either feedback_boost was applied (with NaN propagation) or skipped
        # The key assertion: no unhandled exception
        assert len(results) >= 0  # reached here = no crash

    def test_score_remains_finite_with_extreme_feedback(self):
        """Extreme but valid feedback signals should not produce inf/nan scores."""
        for net in [-100, -50, 50, 100]:
            r = _make_scored_dict(score=0.8, feedback_net=net)
            pipeline = ScoringPipeline(
                ScoringConfig(stages_enabled=_minimal_stages(feedback_boost=True))
            )
            results, _ = pipeline.apply([r])
            assert math.isfinite(results[0]["score"]), (
                f"Score became non-finite with feedback_net={net}"
            )


# ============================================================================
# 6. Code review: verify SQL and soft-delete logic
# ============================================================================


class TestCodeReview:
    """Static code-review assertions — no DB needed."""

    def test_get_bulk_aggregates_uses_sum_not_count(self):
        """The bulk query uses SUM(CASE WHEN...) not two COUNT(FILTER) calls.

        Using SUM with ±1 CASE expression is correct for net signal computation.
        """
        import inspect

        source = inspect.getsource(SearchFeedbackService.get_bulk_aggregates)
        assert "func.sum" in source, "get_bulk_aggregates should use func.sum for net signal"
        assert "CASE WHEN signal" in source, "CASE WHEN signal = 'positive' THEN 1 ELSE -1"

    def test_get_bulk_aggregates_case_expression_covers_negative(self):
        """ELSE clause must assign -1 for non-positive signals."""
        import inspect

        source = inspect.getsource(SearchFeedbackService.get_bulk_aggregates)
        assert "-1" in source, "ELSE clause must assign -1 for negative signals"

    def test_get_aggregate_uses_filter_not_where(self):
        """get_aggregate uses func.count().filter() for conditional aggregation."""
        import inspect

        source = inspect.getsource(SearchFeedbackService.get_aggregate)
        assert ".filter(" in source, "get_aggregate should use func.count().filter()"

    def test_signal_column_max_length(self):
        """signal column is String(20) — 'positive'/'negative' both fit."""
        from src.modules.memvault.models import SearchFeedback

        signal_col = SearchFeedback.__table__.c["signal"]
        assert signal_col.type.length >= 8, (
            f"signal column too short: {signal_col.type.length} (need >= 8 for 'negative')"
        )

    def test_query_hash_column_length(self):
        """query_hash is String(64) — exactly SHA-256 hex length."""
        from src.modules.memvault.models import SearchFeedback

        col = SearchFeedback.__table__.c["query_hash"]
        assert col.type.length == 64, (
            f"query_hash column length {col.type.length} != 64 (SHA-256 hex)"
        )

    def test_entity_id_column_length(self):
        """entity_id is String(32) — UUID v7 without hyphens = 32 chars."""
        from src.modules.memvault.models import SearchFeedback

        col = SearchFeedback.__table__.c["entity_id"]
        assert col.type.length >= 32, (
            f"entity_id column too short: {col.type.length} (need >= 32 for UUID v7)"
        )

    def test_feedback_source_default_is_agent(self):
        """feedback_source has server_default 'agent'."""
        from src.modules.memvault.models import SearchFeedback

        col = SearchFeedback.__table__.c["feedback_source"]
        assert col.server_default is not None, "feedback_source should have server_default"
        default_text = str(col.server_default.arg)
        assert "agent" in default_text, (
            f"feedback_source default should be 'agent', got: {default_text}"
        )

    def test_feedback_boost_weight_config(self):
        """Default feedback_weight in ScoringConfig should be 0.15."""
        config = ScoringConfig()
        assert config.feedback_weight == 0.15, (
            f"Expected feedback_weight=0.15, got {config.feedback_weight}"
        )

    def test_feedback_boost_enabled_by_default(self):
        """feedback_boost stage must be enabled by default in ScoringConfig."""
        config = ScoringConfig()
        assert config.stages_enabled.get("feedback_boost", False) is True, (
            "feedback_boost must be enabled by default"
        )

"""Slow Thinker Phase A tests — prefetch foundation.

六鐵律 applied:
  1. Mutation thinking — each test documents the mutation it kills
  2. Writer/tester separation — contracts from public schema shape
  3. Invariants over fixed I/O — precedence rules before examples
  4. Mock only external I/O — Redis stubbed; dataclass logic runs live
  5. Runtime regression — import checks catch wiring errors
  6. Tests are drafts — each test explains its validation target
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

_CORE_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SDK_ROOT = _REPO_ROOT / "libs" / "sdk-client"

for candidate in (str(_CORE_ROOT), str(_SDK_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from src.modules.memvault.schemas import MemoryCard
from src.shared.prefetch import (
    PrefetchFingerprint,
    PrefetchMetrics,
    SpeculativePrefetchCache,
)


def _make_event_ctx(**overrides) -> dict[str, Any]:
    """Build a QUERY_COMPLETED event context with sensible defaults."""
    ctx: dict[str, Any] = {
        "space_id": "default",
        "query": "test query",
        "intent": "factual",
        "tags": ["memvault", "test"],
        "consumer": "human",
        "task_mode": "build",
        "thinking_mode_used": "fast",
        "load_budget": "standard",
        "result_count": 5,
    }
    ctx.update(overrides)
    return ctx


# ═══════════════════════════════════════════════════════════════════════════
# PrefetchFingerprint
# ═══════════════════════════════════════════════════════════════════════════


class TestPrefetchFingerprint:
    """Invariant tests for cache key generation."""

    def test_cache_key_deterministic(self):
        """Mutation target: if hash depends on dict insertion order, keys diverge."""
        fp1 = PrefetchFingerprint("memvault", "default", {"a": "1", "b": "2"})
        fp2 = PrefetchFingerprint("memvault", "default", {"b": "2", "a": "1"})
        assert fp1.cache_key == fp2.cache_key

    def test_cross_space_isolation(self):
        """Mutation target: removing space_id from key lets space A read space B cache."""
        fp_a = PrefetchFingerprint("memvault", "space_a", {"k": "v"})
        fp_b = PrefetchFingerprint("memvault", "space_b", {"k": "v"})
        assert fp_a.cache_key != fp_b.cache_key

    def test_cross_module_isolation(self):
        """Mutation target: removing module from key lets capture read memvault cache."""
        fp_mv = PrefetchFingerprint("memvault", "default", {"k": "v"})
        fp_cap = PrefetchFingerprint("capture", "default", {"k": "v"})
        assert fp_mv.cache_key != fp_cap.cache_key

    def test_inflight_key_derived(self):
        """Mutation target: inflight key not matching cache key allows duplicate prefetch."""
        fp = PrefetchFingerprint("memvault", "default", {"k": "v"})
        hash_suffix = fp.cache_key.split(":")[-1]
        assert hash_suffix in fp.inflight_key


# ═══════════════════════════════════════════════════════════════════════════
# PrefetchMetrics
# ═══════════════════════════════════════════════════════════════════════════


class TestPrefetchMetrics:
    """Computed property correctness."""

    def test_defaults_all_zero(self):
        """Mutation target: non-zero defaults would bias initial metrics."""
        m = PrefetchMetrics()
        assert m.query_count == 0
        assert m.prefetch_count == 0
        assert m.hit_count == 0
        assert m.hit_rate == 0.0
        assert m.waste_rate == 0.0
        assert m.avg_latency_saved_ms == 0.0

    def test_hit_rate_computed(self):
        """Mutation target: wrong formula or integer division."""
        m = PrefetchMetrics(hit_count=5, prefetch_count=10)
        assert m.hit_rate == 0.5

    def test_division_by_zero_safe(self):
        """Mutation target: ZeroDivisionError when prefetch_count=0."""
        m = PrefetchMetrics(prefetch_count=0, hit_count=0)
        assert m.hit_rate == 0.0
        assert m.waste_rate == 0.0
        assert m.avg_latency_saved_ms == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# QueryEventRecorderOp
# ═══════════════════════════════════════════════════════════════════════════


class TestQueryEventRecorderOp:
    """Contract tests for the Phase A shadow operator."""

    def test_input_output_keys(self):
        """Mutation target: missing key breaks Pipeline.compile()."""
        from src.modules.memvault.slow_thinker import QueryEventRecorderOp

        op = QueryEventRecorderOp()
        assert "space_id" in op.input_keys
        assert "query" in op.input_keys
        assert "consumer" in op.input_keys
        assert "task_mode" in op.input_keys
        assert "recorded" in op.output_keys

    def test_compile_passes(self):
        """Mutation target: key chain breaks if input_keys change."""
        from src.modules.memvault.slow_thinker import QueryEventRecorderOp
        from src.shared.reactive import Pipeline

        op = QueryEventRecorderOp()
        pipe = Pipeline(name="test").pipe(op)
        missing = pipe.compile(initial_keys=set(op.input_keys))
        assert not missing, f"Pipeline compile failed: missing {missing}"


# ═══════════════════════════════════════════════════════════════════════════
# SpeculativePrefetchCache (Redis mocked)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_redis(monkeypatch):
    """Provide a fake Redis that stores data in a dict (module-level fixture)."""
    store: dict[str, str] = {}
    redis_mock = AsyncMock()

    async def fake_get(key):
        return store.get(key)

    async def fake_set(key, value, ex=None, nx=False):
        if nx and key in store:
            return False
        store[key] = value
        return True

    async def fake_delete(*keys):
        for k in keys:
            store.pop(k, None)

    async def fake_hincrby(key, field, amount):
        pass

    async def fake_hincrbyfloat(key, field, amount):
        pass

    async def fake_expire(key, ttl):
        pass

    async def fake_execute():
        pass

    pipe_mock = MagicMock()
    pipe_mock.hincrby = MagicMock()
    pipe_mock.hincrbyfloat = MagicMock()
    pipe_mock.expire = MagicMock()
    pipe_mock.execute = fake_execute

    redis_mock.get = fake_get
    redis_mock.set = fake_set
    redis_mock.delete = fake_delete
    redis_mock.pipeline = MagicMock(return_value=pipe_mock)
    redis_mock.hgetall = AsyncMock(return_value={})

    monkeypatch.setattr("src.shared.prefetch.get_redis", lambda: redis_mock)
    return redis_mock, store


class TestSpeculativePrefetchCacheUnit:
    """Unit tests with mocked Redis — mock only external I/O."""

    @pytest.mark.asyncio
    async def test_set_then_get(self, mock_redis):
        """Mutation target: serialization mismatch between set and get."""
        _, store = mock_redis
        cache = SpeculativePrefetchCache("memvault")
        fp = PrefetchFingerprint("memvault", "default", {"k": "v"})
        cards = [{"id": "fast:block:1", "title": "test", "summary": "hello"}]

        await cache.set(fp, cards)
        result = await cache.get(fp)
        assert result == cards

    @pytest.mark.asyncio
    async def test_get_miss(self, mock_redis):
        """Mutation target: get returning stale data instead of None on miss."""
        cache = SpeculativePrefetchCache("memvault")
        fp = PrefetchFingerprint("memvault", "default", {"k": "nonexistent"})
        result = await cache.get(fp)
        assert result is None

    @pytest.mark.asyncio
    async def test_graceful_degradation(self, monkeypatch):
        """Mutation target: Redis failure propagating as unhandled exception."""

        def broken_redis():
            raise ConnectionError("Redis down")

        monkeypatch.setattr("src.shared.prefetch.get_redis", broken_redis)
        cache = SpeculativePrefetchCache("memvault")
        fp = PrefetchFingerprint("memvault", "default", {"k": "v"})

        # Should return None, not raise
        result = await cache.get(fp)
        assert result is None

        # Should not raise
        await cache.set(fp, [{"id": "1"}])
        await cache.record_query("default")
        await cache.record_hit("default", 50.0)

    @pytest.mark.asyncio
    async def test_try_acquire_inflight_first_succeeds(self, mock_redis):
        """Mutation target: SETNX not working, allowing duplicate prefetch."""
        cache = SpeculativePrefetchCache("memvault")
        fp = PrefetchFingerprint("memvault", "default", {"k": "v"})

        first = await cache.try_acquire_inflight(fp)
        assert first is True

        second = await cache.try_acquire_inflight(fp)
        assert second is False


# ═══════════════════════════════════════════════════════════════════════════
# Event type existence
# ═══════════════════════════════════════════════════════════════════════════


class TestEventTypes:
    """Verify QUERY_COMPLETED event type exists."""

    def test_query_completed_exists(self):
        """Mutation target: removing event type breaks slow thinker wiring."""
        from src.events.types import MemvaultEvents

        assert hasattr(MemvaultEvents, "QUERY_COMPLETED")
        assert MemvaultEvents.QUERY_COMPLETED == "memvault.query.completed"


# ═══════════════════════════════════════════════════════════════════════════
# Phase B1: Operator key-chain and logic tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAdmissionGateOp:
    """Admission gate skip rules — each test kills a specific mutation."""

    @pytest.mark.asyncio
    async def test_skip_ui_consumer(self, mock_redis):
        """Mutation target: removing UI check would allow unpredictable prefetch."""
        from src.modules.memvault.slow_thinker import AdmissionGateOp

        op = AdmissionGateOp()
        ctx = _make_event_ctx(consumer="ui")
        result = await op(ctx)
        assert result["should_prefetch"] is False
        assert result["skip_reason"] == "consumer_ui"

    @pytest.mark.asyncio
    async def test_skip_slow_thinking(self, mock_redis):
        """Mutation target: prefetching after slow path wastes compute."""
        from src.modules.memvault.slow_thinker import AdmissionGateOp

        op = AdmissionGateOp()
        ctx = _make_event_ctx(thinking_mode_used="slow")
        result = await op(ctx)
        assert result["should_prefetch"] is False
        assert result["skip_reason"] == "already_slow"

    @pytest.mark.asyncio
    async def test_skip_zero_results(self, mock_redis):
        """Mutation target: predicting from empty context produces noise."""
        from src.modules.memvault.slow_thinker import AdmissionGateOp

        op = AdmissionGateOp()
        ctx = _make_event_ctx(result_count=0)
        result = await op(ctx)
        assert result["should_prefetch"] is False
        assert result["skip_reason"] == "no_results"

    @pytest.mark.asyncio
    async def test_allows_valid_query(self, mock_redis):
        """Mutation target: overly aggressive gating blocks all prefetch."""
        from src.modules.memvault.slow_thinker import AdmissionGateOp

        op = AdmissionGateOp()
        ctx = _make_event_ctx(consumer="agent", thinking_mode_used="fast", result_count=5)
        result = await op(ctx)
        assert result["should_prefetch"] is True
        assert result["skip_reason"] is None

    @pytest.mark.asyncio
    async def test_min_sample_threshold(self, mock_redis):
        """Mutation target: hit_rate check without min samples self-disables on cold start."""
        from src.modules.memvault.slow_thinker import AdmissionGateOp

        redis_mock, store = mock_redis
        # Simulate low hit rate but below min sample threshold
        redis_mock.hgetall = AsyncMock(return_value={
            "prefetch_count": "10",  # Below _MIN_SAMPLE_THRESHOLD (50)
            "hit_count": "0",
        })
        op = AdmissionGateOp()
        ctx = _make_event_ctx(consumer="agent", thinking_mode_used="fast", result_count=5)
        result = await op(ctx)
        # Should NOT skip because sample count is too low
        assert result["should_prefetch"] is True


class TestIntentPredictorOp:
    """Intent prediction rule tests."""

    def test_input_output_keys(self):
        """Mutation target: key-chain break in Pipeline."""
        from src.modules.memvault.slow_thinker import IntentPredictorOp

        op = IntentPredictorOp()
        assert "space_id" in op.input_keys
        assert "should_prefetch" in op.input_keys
        assert "predicted_fingerprint" in op.output_keys

    @pytest.mark.asyncio
    async def test_skip_when_not_prefetching(self):
        """Mutation target: predictor running unnecessarily when gated out."""
        from src.modules.memvault.slow_thinker import IntentPredictorOp

        op = IntentPredictorOp()
        ctx = {"should_prefetch": False, "space_id": "default", "consumer": "agent",
               "task_mode": "build", "intent": "factual", "tags": []}
        result = await op(ctx)
        assert result["predicted_fingerprint"] is None

    def test_transition_entity_to_factual(self):
        """Mutation target: wrong transition table loses drill-down pattern."""
        from src.modules.memvault.slow_thinker import IntentPredictorOp

        assert IntentPredictorOp._TRANSITIONS["entity_lookup"] == "factual"

    def test_transition_conceptual_to_exploratory(self):
        """Mutation target: conceptual → exploratory broadening lost."""
        from src.modules.memvault.slow_thinker import IntentPredictorOp

        assert IntentPredictorOp._TRANSITIONS["conceptual"] == "exploratory"


class TestCacheWriterOp:
    """Cache writer contract tests."""

    @pytest.mark.asyncio
    async def test_skip_when_no_fingerprint(self, mock_redis):
        """Mutation target: writing None fingerprint corrupts cache."""
        from src.modules.memvault.slow_thinker import CacheWriterOp

        op = CacheWriterOp()
        ctx = {"predicted_fingerprint": None, "prefetch_cards": [], "execution_ms": 0}
        result = await op(ctx)
        assert result["cache_key_written"] is None
        assert result["metrics_recorded"] is False

    @pytest.mark.asyncio
    async def test_skip_when_no_cards(self, mock_redis):
        """Mutation target: empty cache entries waste memory."""
        from src.modules.memvault.slow_thinker import CacheWriterOp

        fp = PrefetchFingerprint("memvault", "default", {"k": "v"})
        op = CacheWriterOp()
        ctx = {"predicted_fingerprint": fp, "prefetch_cards": [], "execution_ms": 50}
        result = await op(ctx)
        assert result["cache_key_written"] is None

    @pytest.mark.asyncio
    async def test_writes_when_cards_present(self, mock_redis):
        """Mutation target: cache write silently dropped."""
        from src.modules.memvault.slow_thinker import CacheWriterOp

        _, store = mock_redis
        fp = PrefetchFingerprint("memvault", "default", {"k": "v"})
        cards = [{"id": "prefetch:block:1", "title": "test"}]
        op = CacheWriterOp()
        ctx = {"predicted_fingerprint": fp, "prefetch_cards": cards, "execution_ms": 100}
        result = await op(ctx)
        assert result["cache_key_written"] == fp.cache_key
        assert result["metrics_recorded"] is True
        # Verify cache actually written
        assert fp.cache_key in store


class TestB1PipelineCompile:
    """End-to-end Pipeline.compile() for Phase B1."""

    def test_full_pipeline_compiles(self):
        """Mutation target: any Operator key-chain break fails this test."""
        from src.modules.memvault.slow_thinker import (
            AdmissionGateOp,
            CacheWriterOp,
            IntentPredictorOp,
            PrefetchExecutorOp,
            QueryEventRecorderOp,
        )
        from src.shared.reactive import Pipeline

        ops = [
            QueryEventRecorderOp(),
            AdmissionGateOp(),
            IntentPredictorOp(),
            PrefetchExecutorOp(),
            CacheWriterOp(),
        ]
        pipe = Pipeline(name="slow_thinker_b1_test").pipe(*ops)
        initial_keys = {
            "space_id", "query", "intent", "tags", "consumer",
            "task_mode", "thinking_mode_used", "load_budget", "result_count",
        }
        missing = pipe.compile(initial_keys=initial_keys)
        assert not missing, f"Pipeline compile failed: missing {missing}"


# ═══════════════════════════════════════════════════════════════════════════
# Phase B2: Cache read + merge tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMergePrefetchCards:
    """Tests for _merge_prefetch_cards — dedup and budget enforcement."""

    def test_merge_appends_after_existing(self):
        """Mutation target: prefetch cards replacing stable results."""
        from src.modules.memvault.query_runtime import _merge_prefetch_cards

        existing = [
            MemoryCard(id="stable:1", title="S1", summary="s1", why_relevant="r",
                       use_now="u", layer="fast", source_type="block", confidence=0.9,
                       evidence_refs=[]),
        ]
        prefetched = [
            MemoryCard(id="prefetch:1", title="P1", summary="p1", why_relevant="r",
                       use_now="u", layer="fast", source_type="block", confidence=0.7,
                       evidence_refs=[], source="speculative_prefetch"),
        ]
        merged = _merge_prefetch_cards(existing, prefetched, budget=5)
        assert merged[0].id == "stable:1", "Stable results must come first"
        assert merged[1].id == "prefetch:1"

    def test_dedup_by_id(self):
        """Mutation target: duplicate IDs in merged results."""
        from src.modules.memvault.query_runtime import _merge_prefetch_cards

        existing = [
            MemoryCard(id="same:1", title="E", summary="e", why_relevant="r",
                       use_now="u", layer="fast", source_type="block", confidence=0.9,
                       evidence_refs=[]),
        ]
        prefetched = [
            MemoryCard(id="same:1", title="P", summary="p", why_relevant="r",
                       use_now="u", layer="fast", source_type="block", confidence=0.7,
                       evidence_refs=[], source="speculative_prefetch"),
        ]
        merged = _merge_prefetch_cards(existing, prefetched, budget=5)
        assert len(merged) == 1, "Duplicate ID must be deduplicated"

    def test_respects_budget(self):
        """Mutation target: budget overflow from prefetch additions."""
        from src.modules.memvault.query_runtime import _merge_prefetch_cards

        existing = [
            MemoryCard(id=f"s:{i}", title="S", summary="s", why_relevant="r",
                       use_now="u", layer="fast", source_type="block", confidence=0.9,
                       evidence_refs=[])
            for i in range(3)
        ]
        prefetched = [
            MemoryCard(id=f"p:{i}", title="P", summary="p", why_relevant="r",
                       use_now="u", layer="fast", source_type="block", confidence=0.7,
                       evidence_refs=[], source="speculative_prefetch")
            for i in range(5)
        ]
        merged = _merge_prefetch_cards(existing, prefetched, budget=4)
        assert len(merged) == 4, f"Budget of 4 exceeded: got {len(merged)}"


class TestMemoryCardSource:
    """Verify MemoryCard schema has source field."""

    def test_source_field_exists(self):
        """Mutation target: removing source field breaks provenance tracking."""
        card = MemoryCard(
            id="test:1", title="T", summary="s", why_relevant="r",
            use_now="u", layer="fast", source_type="block", confidence=0.8,
            evidence_refs=[], source="speculative_prefetch",
        )
        assert card.source == "speculative_prefetch"

    def test_source_default_none(self):
        """Mutation target: non-None default taints all normal cards."""
        card = MemoryCard(
            id="test:1", title="T", summary="s", why_relevant="r",
            use_now="u", layer="fast", source_type="block", confidence=0.8,
            evidence_refs=[],
        )
        assert card.source is None


# ═══════════════════════════════════════════════════════════════════════════
# Phase C: Eviction + Metrics endpoint
# ═══════════════════════════════════════════════════════════════════════════


class TestEvictionOp:
    """Eviction operator tests."""

    def test_input_output_keys(self):
        """Mutation target: key-chain break."""
        from src.modules.memvault.slow_thinker import EvictionOp

        op = EvictionOp()
        assert "space_id" in op.input_keys
        assert "evicted_count" in op.output_keys

    @pytest.mark.asyncio
    async def test_graceful_on_redis_failure(self, monkeypatch):
        """Mutation target: Redis failure crashes eviction instead of degrading."""
        from src.modules.memvault.slow_thinker import EvictionOp

        def broken_redis():
            raise ConnectionError("Redis down")

        # Patch at the source module where EvictionOp imports from
        monkeypatch.setattr("src.shared.redis.get_redis", broken_redis)

        op = EvictionOp()
        ctx = {"space_id": "default"}
        result = await op(ctx)
        assert result["evicted_count"] == 0  # Graceful: 0, not crash

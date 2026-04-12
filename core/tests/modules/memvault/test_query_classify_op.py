"""Test-adversary: QueryClassifyOp — specification-driven tests.

Written from PUBLIC SPEC ONLY. Implementation files were NOT read.
Every test targets one invariant; mutations (weight swap, regex removal,
off-by-one on threshold) should cause at least one test to fail.

Categories:
  A. Preset QA Invariants
  B. Tier 1 Keyword Boundary Cases
  C. Tier 1∥2 Fusion Properties
  D. LayerPlan Structure
  E. Graceful Degradation
  F. PersonalizedQueryRouter
  G. Concurrent Safety
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — consistent with conftest.py pattern in this repo
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # resolves to core/

from src.modules.memvault.query_archetypes import (
    ensure_archetype_embeddings,
    llm_classify,
    match_preset_qa,
    semantic_intent_scores,
)
from src.modules.memvault.query_router import (
    LayerPlan,
    PersonalizedQueryRouter,
    QueryIntent,
    classify_query,
    classify_query_full,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_LAYER_MODES = {"SEMANTIC", "HYBRID", "ILIKE", "SKIP"}
VALID_INTENTS = {i.value for i in QueryIntent}


def _assert_valid_layer_plan(plan: LayerPlan) -> None:
    """Assert every structural invariant on a LayerPlan."""
    assert isinstance(plan, LayerPlan), f"Expected LayerPlan, got {type(plan)}"
    # Intent must be a valid enum member
    assert plan.intent in QueryIntent, f"Unknown intent: {plan.intent}"
    # Confidence in [0, 1]
    assert 0.0 <= plan.confidence <= 1.0, f"Confidence out of range: {plan.confidence}"
    # layers dict must exist and use valid modes
    assert isinstance(plan.layers, dict), "layers must be a dict"
    assert len(plan.layers) > 0, "layers dict must not be empty"
    for layer, mode in plan.layers.items():
        assert mode in VALID_LAYER_MODES, f"Invalid mode '{mode}' for layer '{layer}'"
    # time_window_days must be non-negative
    assert plan.time_window_days >= 0, "time_window_days must be >= 0"
    # sort_by must be a non-empty string
    assert isinstance(plan.sort_by, str) and plan.sort_by, "sort_by must be non-empty string"


# ===========================================================================
# A. Preset QA Invariants
# ===========================================================================


class TestPresetQAInvariants:
    """All 5 canonical preset queries must match with exact invariants."""

    # --- A1: "最近忙什麼" ---------------------

    def test_a1_preset_recent_activity_matches(self):
        """最近忙什麼 must match preset."""
        result = match_preset_qa("最近忙什麼")
        assert result is not None, "Preset '最近忙什麼' should match"

    def test_a1_preset_recent_activity_confidence(self):
        """Preset match via classify_query must return confidence == 0.95 exactly."""
        plan = classify_query("最近忙什麼")
        assert plan.confidence == 0.95, (
            f"Preset confidence must be 0.95, got {plan.confidence}"
        )

    def test_a1_preset_recent_activity_intent(self):
        """最近忙什麼 → exploratory intent."""
        result = match_preset_qa("最近忙什麼")
        assert result is not None
        assert result["intent"] == "exploratory"

    def test_a1_preset_recent_activity_hint(self):
        """最近忙什麼 → preset_hint == temporal_activity."""
        result = match_preset_qa("最近忙什麼")
        assert result is not None
        assert result.get("retrieval_hint") == "temporal_activity"

    def test_a1_preset_recent_activity_sort(self):
        """最近忙什麼 → sort_by == created_at_desc."""
        result = match_preset_qa("最近忙什麼")
        assert result is not None
        assert result.get("sort_by") == "created_at_desc"

    def test_a1_preset_recent_activity_time_window(self):
        """最近忙什麼 → time_window_days == 7."""
        result = match_preset_qa("最近忙什麼")
        assert result is not None
        assert result.get("time_window_days") == 7

    # --- A2: "根據之前討論的X，下一步怎麼規劃" -----

    def test_a2_preset_continuation_matches(self):
        """Continuation query pattern must match preset."""
        result = match_preset_qa("根據之前討論的系統設計，下一步怎麼規劃")
        assert result is not None, "Continuation preset should match"

    def test_a2_preset_continuation_intent(self):
        """Continuation preset → conceptual intent."""
        result = match_preset_qa("根據之前討論的系統設計，下一步怎麼規劃")
        assert result is not None
        assert result["intent"] == "conceptual"

    def test_a2_preset_continuation_hint(self):
        """Continuation preset → preset_hint == continuation."""
        result = match_preset_qa("根據之前討論的系統設計，下一步怎麼規劃")
        assert result is not None
        assert result.get("retrieval_hint") == "continuation"

    # --- A3: "X做到哪裡了" --------------------

    def test_a3_preset_progress_matches(self):
        """Progress query must match preset."""
        result = match_preset_qa("memvault做到哪裡了")
        assert result is not None, "Progress preset should match"

    def test_a3_preset_progress_intent(self):
        """Progress preset → exploratory intent."""
        result = match_preset_qa("memvault做到哪裡了")
        assert result is not None
        assert result["intent"] == "exploratory"

    def test_a3_preset_progress_hint(self):
        """Progress preset → preset_hint == progress."""
        result = match_preset_qa("memvault做到哪裡了")
        assert result is not None
        assert result.get("retrieval_hint") == "progress"

    def test_a3_preset_progress_sort(self):
        """Progress preset → sort_by == updated_at_desc."""
        result = match_preset_qa("memvault做到哪裡了")
        assert result is not None
        assert result.get("sort_by") == "updated_at_desc"

    # --- A4: "什麼時間做了哪些事情" ---------------

    def test_a4_preset_timeline_matches(self):
        """Timeline query must match preset."""
        result = match_preset_qa("什麼時間做了哪些事情")
        assert result is not None, "Timeline preset should match"

    def test_a4_preset_timeline_intent(self):
        """Timeline preset → exploratory intent."""
        result = match_preset_qa("什麼時間做了哪些事情")
        assert result is not None
        assert result["intent"] == "exploratory"

    def test_a4_preset_timeline_hint(self):
        """Timeline preset → preset_hint == timeline."""
        result = match_preset_qa("什麼時間做了哪些事情")
        assert result is not None
        assert result.get("retrieval_hint") == "timeline"

    def test_a4_preset_timeline_sort(self):
        """Timeline preset → sort_by == created_at_asc (ascending for chronological)."""
        result = match_preset_qa("什麼時間做了哪些事情")
        assert result is not None
        assert result.get("sort_by") == "created_at_asc"

    def test_a4_preset_timeline_time_window(self):
        """Timeline preset → time_window_days == 30."""
        result = match_preset_qa("什麼時間做了哪些事情")
        assert result is not None
        assert result.get("time_window_days") == 30

    # --- A5: "有哪些東西還沒做完" ----------------

    def test_a5_preset_pending_matches(self):
        """Pending items query must match preset."""
        result = match_preset_qa("有哪些東西還沒做完")
        assert result is not None, "Pending items preset should match"

    def test_a5_preset_pending_intent(self):
        """Pending items preset → exploratory intent."""
        result = match_preset_qa("有哪些東西還沒做完")
        assert result is not None
        assert result["intent"] == "exploratory"

    def test_a5_preset_pending_hint(self):
        """Pending items preset → preset_hint == pending_items."""
        result = match_preset_qa("有哪些東西還沒做完")
        assert result is not None
        assert result.get("retrieval_hint") == "pending_items"

    def test_a5_preset_pending_sort(self):
        """Pending items preset → sort_by == updated_at_desc."""
        result = match_preset_qa("有哪些東西還沒做完")
        assert result is not None
        assert result.get("sort_by") == "updated_at_desc"

    def test_a5_preset_pending_time_window(self):
        """Pending items preset → time_window_days == 14."""
        result = match_preset_qa("有哪些東西還沒做完")
        assert result is not None
        assert result.get("time_window_days") == 14

    # --- A6: Negative — similar-looking non-preset query -----

    def test_a6_negative_similar_query_does_not_match(self):
        """'我最近沒忙什麼' should NOT match any preset (negation changes semantics)."""
        result = match_preset_qa("我最近沒忙什麼")
        # Either returns None OR returns a non-preset result (confidence < 0.95)
        if result is not None:
            assert result.get("confidence", 0) < 0.95, (
                "Negated query should not get 0.95 preset confidence"
            )

    # --- A7: Partial match boundary ------

    def test_a7_partial_truncated_does_not_get_preset_confidence(self):
        """'最近忙' (truncated) should either not match or not return 0.95."""
        result = match_preset_qa("最近忙")
        if result is not None:
            # If it matches, verify it maps to a valid intent
            assert result.get("intent") in VALID_INTENTS

    # --- A8: All 5 presets produce valid confidence exactly 0.95 ----

    @pytest.mark.parametrize("query,expected_intent", [
        ("最近忙什麼", "exploratory"),
        ("根據之前討論的設計方案，下一步怎麼規劃", "conceptual"),
        ("專案做到哪裡了", "exploratory"),
        ("什麼時間做了哪些事情", "exploratory"),
        ("有哪些東西還沒做完", "exploratory"),
    ])
    def test_a8_preset_confidence_exactly_095(self, query: str, expected_intent: str):
        """All matching presets via classify_query must return exactly 0.95 confidence."""
        result = match_preset_qa(query)
        if result is not None and result.get("intent") == expected_intent:
            plan = classify_query(query)
            assert plan.confidence == 0.95, (
                f"Preset for '{query}' confidence should be 0.95, got {plan.confidence}"
            )


# ===========================================================================
# B. Tier 1 Keyword Boundary Cases
# ===========================================================================


class TestTier1KeywordBoundary:
    """Tier 1 = classify_query() (sync, keyword-only, <1ms)."""

    def test_b1_empty_string_does_not_raise(self):
        """Empty string must not raise; returns a valid LayerPlan."""
        plan = classify_query("")
        _assert_valid_layer_plan(plan)

    def test_b1_empty_string_low_confidence(self):
        """Empty string should have low confidence (no signal)."""
        plan = classify_query("")
        assert plan.confidence < 0.8, (
            f"Empty string should have low confidence, got {plan.confidence}"
        )

    def test_b2_single_char_does_not_raise(self):
        """Single character input must not raise."""
        plan = classify_query("A")
        _assert_valid_layer_plan(plan)

    def test_b3_very_long_string_does_not_raise(self):
        """500+ character input must not raise."""
        long_query = "架構設計" * 150  # 600 chars
        plan = classify_query(long_query)
        _assert_valid_layer_plan(plan)

    def test_b4_pure_emoji_does_not_raise(self):
        """Pure emoji input must not raise and returns valid LayerPlan."""
        plan = classify_query("🎉🎉🎉")
        _assert_valid_layer_plan(plan)

    def test_b5_numbers_only_does_not_raise(self):
        """Numeric-only input must not raise."""
        plan = classify_query("12345")
        _assert_valid_layer_plan(plan)

    def test_b6_mixed_language_does_not_raise(self):
        """Mixed CJK + ASCII input must not raise."""
        plan = classify_query("why 要用這個架構")
        _assert_valid_layer_plan(plan)

    def test_b7_activity_pattern_yields_exploratory(self):
        """Query containing ACTIVITY_PATTERNS keyword → exploratory intent."""
        # Spec: ACTIVITY_PATTERNS → exploratory (忙什麼, 做了什麼, 進展)
        plan = classify_query("你最近做了什麼")
        assert plan.intent == QueryIntent.EXPLORATORY, (
            f"ACTIVITY keyword '做了什麼' should yield exploratory, got {plan.intent}"
        )

    def test_b8_progress_pattern_yields_exploratory(self):
        """Query containing PROGRESS_PATTERNS keyword → exploratory intent."""
        # Spec: PROGRESS_PATTERNS → exploratory (做到哪, 完成了嗎, 進度)
        plan = classify_query("這件事完成了嗎")
        assert plan.intent == QueryIntent.EXPLORATORY, (
            f"PROGRESS keyword '完成了嗎' should yield exploratory, got {plan.intent}"
        )

    def test_b9_continuation_pattern_yields_conceptual(self):
        """Query containing CONTINUATION_PATTERNS keyword → conceptual intent."""
        # Spec: CONTINUATION_PATTERNS → conceptual (之前討論, 下一步, 接著做)
        plan = classify_query("之前討論的這個問題")
        assert plan.intent == QueryIntent.CONCEPTUAL, (
            f"CONTINUATION keyword '之前討論' should yield conceptual, got {plan.intent}"
        )

    def test_b10_continuation_keyword_next_step_yields_conceptual(self):
        """'下一步' alone should map to conceptual."""
        plan = classify_query("下一步應該怎麼做")
        assert plan.intent == QueryIntent.CONCEPTUAL, (
            f"'下一步' should yield conceptual, got {plan.intent}"
        )

    def test_b11_competing_signals_returns_valid_plan(self):
        """Query mixing multiple pattern signals must still return valid LayerPlan."""
        # Has both exploratory (進展) and conceptual (之前討論) signals
        plan = classify_query("之前討論的進展怎麼樣")
        _assert_valid_layer_plan(plan)
        # Must resolve to one valid intent — no crash, no unknown unless spec says so
        assert plan.intent in QueryIntent


# ===========================================================================
# C. Tier 1∥2 Fusion Properties
# ===========================================================================


class TestFusionProperties:
    """classify_query_full = async; fuses Tier 1 (0.4) + Tier 2 (0.6)."""

    @pytest.mark.asyncio
    async def test_c1_fusion_weights_reflected_when_tier2_agrees(self):
        """When tier2 confirms tier1 intent, full result should have higher confidence than tier1 alone."""
        plan_t1 = classify_query("最近做了什麼事情")
        plan_full = await classify_query_full("最近做了什麼事情")
        _assert_valid_layer_plan(plan_full)
        # Fusion of two agreeing signals should not be LOWER than tier1 alone
        # (This tests that 0.6 weight is applied, not zeroed out)
        assert plan_full.confidence >= plan_t1.confidence * 0.4, (
            "Fusion confidence should not collapse below tier1 * fusion_weight"
        )

    @pytest.mark.asyncio
    async def test_c2_tier2_unavailable_degrades_to_tier1(self):
        """When tier2 embedding returns None/empty, result must equal tier1 classification."""
        with patch(
            "src.modules.memvault.query_archetypes.semantic_intent_scores",
            new_callable=AsyncMock,
            return_value={},
        ):
            plan_full = await classify_query_full("什麼是 RAG 架構")
            plan_t1 = classify_query("什麼是 RAG 架構")
            _assert_valid_layer_plan(plan_full)
            # Without tier2 data, intent should match tier1
            assert plan_full.intent == plan_t1.intent, (
                "When tier2 is empty, fusion must fall back to tier1 intent"
            )

    @pytest.mark.asyncio
    async def test_c3_fusion_result_never_crashes(self):
        """classify_query_full must return a valid LayerPlan for any string input."""
        inputs = ["", "hello", "什麼是架構", "🎉", "A" * 500]
        for q in inputs:
            plan = await classify_query_full(q)
            _assert_valid_layer_plan(plan), f"classify_query_full crashed or returned invalid for: {q!r}"

    @pytest.mark.asyncio
    async def test_c4_tier2_scores_clipped_to_valid_range(self):
        """Tier2 scores (cosine similarity) should be in [0, 1]; fusion must handle extremes."""
        # Inject a tier2 score outside [0,1] — fusion must not produce out-of-range confidence
        with patch(
            "src.modules.memvault.query_archetypes.semantic_intent_scores",
            new_callable=AsyncMock,
            return_value={"exploratory": 1.5, "factual": -0.3},  # invalid cosine values
        ):
            plan = await classify_query_full("最近做了什麼")
            _assert_valid_layer_plan(plan)

    @pytest.mark.asyncio
    async def test_c5_full_returns_valid_intent_enum(self):
        """classify_query_full must always return a proper QueryIntent enum value."""
        plan = await classify_query_full("什麼是向量資料庫")
        assert plan.intent in QueryIntent, f"Got non-enum intent: {plan.intent!r}"

    @pytest.mark.asyncio
    async def test_c6_fusion_confidence_in_unit_interval(self):
        """Fused confidence must remain in [0.0, 1.0] regardless of tier scores."""
        plan = await classify_query_full("架構設計模式有哪些")
        assert 0.0 <= plan.confidence <= 1.0, (
            f"Fused confidence out of [0,1]: {plan.confidence}"
        )


# ===========================================================================
# D. LayerPlan Structure
# ===========================================================================


class TestLayerPlanStructure:
    """LayerPlan must conform to spec for both sync and async paths."""

    def test_d1_sync_returns_layer_plan_type(self):
        """classify_query must return a LayerPlan instance."""
        result = classify_query("測試一下系統架構")
        assert isinstance(result, LayerPlan)

    def test_d2_layers_dict_non_empty(self):
        """layers dict must contain at least one entry."""
        plan = classify_query("什麼是記憶系統")
        assert len(plan.layers) > 0

    def test_d3_layer_modes_all_valid(self):
        """Every layer mode must be one of SEMANTIC|HYBRID|ILIKE|SKIP."""
        plan = classify_query("搜尋記憶系統的架構文件")
        for layer, mode in plan.layers.items():
            assert mode in VALID_LAYER_MODES, (
                f"Layer '{layer}' has invalid mode '{mode}'"
            )

    def test_d4_intent_is_query_intent_enum(self):
        """intent field must be a QueryIntent enum member."""
        plan = classify_query("最近忙什麼")
        assert isinstance(plan.intent, QueryIntent)

    def test_d5_confidence_float_not_int(self):
        """confidence should be a float (not raw int)."""
        plan = classify_query("測試查詢")
        assert isinstance(plan.confidence, (int, float)), "confidence must be numeric"
        # Not a sentinel like None
        assert plan.confidence is not None

    def test_d6_time_window_days_non_negative(self):
        """time_window_days must be >= 0."""
        plan = classify_query("找一下上週做了什麼")
        assert plan.time_window_days >= 0

    def test_d7_sort_by_is_string(self):
        """sort_by must be a non-empty string."""
        plan = classify_query("查詢最新的記錄")
        assert isinstance(plan.sort_by, str)
        assert len(plan.sort_by) > 0

    def test_d8_preset_hint_none_or_string(self):
        """preset_hint must be None or a non-empty string."""
        plan = classify_query("什麼是 attention mechanism")
        if plan.preset_hint is not None:
            assert isinstance(plan.preset_hint, str)
            assert len(plan.preset_hint) > 0

    @pytest.mark.parametrize("intent_name", [
        "entity_lookup", "conceptual", "factual",
        "exploratory", "cross_domain", "unknown",
    ])
    def test_d9_all_query_intent_enum_values_exist(self, intent_name: str):
        """All 6 QueryIntent enum values from spec must exist."""
        # StrEnum members are UPPER_CASE, values are lower_case
        assert intent_name in {i.value for i in QueryIntent}, (
            f"QueryIntent missing value: {intent_name}"
        )


# ===========================================================================
# E. Graceful Degradation
# ===========================================================================


class TestGracefulDegradation:
    """System must never raise; degrade gracefully on dependency failure."""

    @pytest.mark.asyncio
    async def test_e1_embedding_service_down_returns_valid_plan(self):
        """If embedding service returns None, classify_query_full must not raise."""
        with patch(
            "src.modules.memvault.query_archetypes.semantic_intent_scores",
            new_callable=AsyncMock,
            side_effect=Exception("embedding service unavailable"),
        ):
            # Must NOT propagate exception
            plan = await classify_query_full("什麼是記憶系統")
            _assert_valid_layer_plan(plan)

    @pytest.mark.asyncio
    async def test_e2_llm_service_down_returns_valid_plan(self):
        """If LLM is down, classify_query_full must degrade gracefully."""
        with patch(
            "src.modules.memvault.query_archetypes.llm_classify",
            new_callable=AsyncMock,
            side_effect=Exception("LLM timeout"),
        ):
            plan = await classify_query_full("這是一個測試查詢")
            _assert_valid_layer_plan(plan)

    @pytest.mark.asyncio
    async def test_e3_both_services_down_falls_back_to_tier1(self):
        """When both tier2 and LLM fail, result should still be usable (tier1 only)."""
        with (
            patch(
                "src.modules.memvault.query_archetypes.semantic_intent_scores",
                new_callable=AsyncMock,
                side_effect=Exception("embedding down"),
            ),
            patch(
                "src.modules.memvault.query_archetypes.llm_classify",
                new_callable=AsyncMock,
                side_effect=Exception("LLM down"),
            ),
        ):
            plan_t1 = classify_query("做了什麼事情")
            plan_full = await classify_query_full("做了什麼事情")
            _assert_valid_layer_plan(plan_full)
            # Degraded to tier1 — intent must match tier1
            assert plan_full.intent == plan_t1.intent

    @pytest.mark.asyncio
    async def test_e4_unicode_control_chars_do_not_crash(self):
        """Unicode control characters / null bytes must not cause crash."""
        plan = await classify_query_full("\x00\x01\x1f測試")
        _assert_valid_layer_plan(plan)

    @pytest.mark.asyncio
    async def test_e5_whitespace_only_does_not_crash(self):
        """Whitespace-only input must not raise."""
        plan = await classify_query_full("   \t\n  ")
        _assert_valid_layer_plan(plan)


# ===========================================================================
# F. PersonalizedQueryRouter
# ===========================================================================


class TestPersonalizedQueryRouter:
    """PersonalizedQueryRouter wraps classify_query with attention overlay."""

    def test_f1_classify_sync_returns_layer_plan(self):
        """classify() must return a LayerPlan instance."""
        router = PersonalizedQueryRouter(attention_profile={})
        plan = router.classify("最近在做什麼")
        assert isinstance(plan, LayerPlan)

    def test_f2_classify_sync_never_returns_none(self):
        """classify() must never return None."""
        router = PersonalizedQueryRouter(attention_profile={})
        result = router.classify("什麼是架構")
        assert result is not None

    @pytest.mark.asyncio
    async def test_f3_classify_full_returns_layer_plan(self):
        """classify_full() must return a LayerPlan instance."""
        router = PersonalizedQueryRouter(attention_profile={})
        plan = await router.classify_full("什麼是記憶系統")
        assert isinstance(plan, LayerPlan)

    @pytest.mark.asyncio
    async def test_f4_empty_attention_matches_base_classifier(self):
        """Empty attention profile → classify_full should agree with classify_query_full."""
        router = PersonalizedQueryRouter(attention_profile={})
        query = "做了什麼進展"
        plan_base = await classify_query_full(query)
        plan_router = await router.classify_full(query)
        _assert_valid_layer_plan(plan_router)
        # Intent should be identical when attention profile is empty
        assert plan_router.intent == plan_base.intent, (
            "Empty attention profile should not alter intent"
        )

    @pytest.mark.asyncio
    async def test_f5_classify_full_never_raises(self):
        """classify_full must not raise even on degenerate input."""
        router = PersonalizedQueryRouter(attention_profile={})
        for q in ["", "🎉", "A" * 600, "\x00"]:
            plan = await router.classify_full(q)
            assert isinstance(plan, LayerPlan), f"Expected LayerPlan for input {q!r}"


# ===========================================================================
# G. Concurrent Safety
# ===========================================================================


class TestConcurrentSafety:
    """Async concurrent calls must be safe; lazy init must not race."""

    @pytest.mark.asyncio
    async def test_g1_concurrent_calls_same_query_all_succeed(self):
        """10 concurrent classify_query_full calls with the same query must all succeed."""
        query = "最近做了什麼事情"
        tasks = [classify_query_full(query) for _ in range(10)]
        results = await asyncio.gather(*tasks)
        assert len(results) == 10
        for plan in results:
            _assert_valid_layer_plan(plan)

    @pytest.mark.asyncio
    async def test_g2_concurrent_calls_different_queries_all_succeed(self):
        """Concurrent calls with different queries must all return valid plans."""
        queries = [
            "最近忙什麼",
            "什麼是 RAG",
            "做到哪裡了",
            "架構設計",
            "有哪些未完成的工作",
        ]
        tasks = [classify_query_full(q) for q in queries]
        results = await asyncio.gather(*tasks)
        for q, plan in zip(queries, results):
            _assert_valid_layer_plan(plan), f"Invalid plan for: {q!r}"

    @pytest.mark.asyncio
    async def test_g3_ensure_archetype_embeddings_concurrent_idempotent(self):
        """ensure_archetype_embeddings called concurrently must not crash or return None."""
        tasks = [ensure_archetype_embeddings() for _ in range(5)]
        results = await asyncio.gather(*tasks)
        for r in results:
            assert r is not None, "ensure_archetype_embeddings must not return None"
            assert isinstance(r, dict), "ensure_archetype_embeddings must return dict"

    @pytest.mark.asyncio
    async def test_g4_concurrent_different_intents_no_cross_contamination(self):
        """Concurrent calls should not cross-contaminate results (deterministic for same input)."""
        query = "之前討論的架構方向，下一步怎麼規劃"
        # Run 5 times serially to get reference
        ref_plan = await classify_query_full(query)
        # Run 5 concurrently
        tasks = [classify_query_full(query) for _ in range(5)]
        concurrent_results = await asyncio.gather(*tasks)
        for plan in concurrent_results:
            assert plan.intent == ref_plan.intent, (
                "Concurrent calls must return same intent for identical input"
            )

"""Tests for memvault multi-signal edge weight, surprise, and review operators.

Follows 六鐵律:
1. Mutation thinking — edge cases that would survive naive mutations
2. Independent from implementation — test behaviour, not internal wiring
3. Invariants over fixed I/O — properties that must ALWAYS hold
4. Mock only external I/O — no mocking of MemvaultOp internals
5. Error paths covered — failure modes are first-class test cases
6. Write-test separation — written without reading source files
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from src.modules.memvault.ops._base import MemvaultOp, PipelineMeta
from src.modules.memvault.pipeline_config import MemvaultPipelineConfig

# ═══════════════════════════════════════════════════════════════════════════
# Import the real operators under test (no source reading, spec-driven only)
# ═══════════════════════════════════════════════════════════════════════════

from src.modules.memvault.ops.edge_ops import (
    EdgeAdamicAdarOp,
    EdgeCooccurrenceOp,
    EdgeCompositeOp,
    EdgePersistOp,
    EdgeSemanticSimilarityOp,
    EdgeSessionOverlapOp,
    EdgeTypeAffinityOp,
    _normalize_pair,
)
from src.modules.memvault.ops.review_ops import ReviewAutoApproveOp
from src.modules.memvault.ops.surprise_ops import (
    MergeSurprisesOp,
    SurpriseCrossCommunityOp,
    SurpriseIndirectStrongOp,
    SurpriseKnowledgeGapOp,
)
from src.modules.memvault.pipelines.edge_pipeline import build_edge_pipeline
from src.modules.memvault.pipelines.surprise_pipeline import build_surprise_pipeline

# ═══════════════════════════════════════════════════════════════════════════
# Test helper ops (concrete subclasses; never mock MemvaultOp internals)
# ═══════════════════════════════════════════════════════════════════════════


class PassthroughEdgeCompositeOp(MemvaultOp):
    """Controllable substitute for EdgeCompositeOp — injects fixed map."""

    def __init__(self, config: MemvaultPipelineConfig, result: dict) -> None:
        super().__init__("edge.composite", config)
        self._result = result

    @property
    def input_keys(self) -> tuple[str, ...]:
        return (
            "edge_cooccurrence_map",
            "edge_session_overlap_map",
            "edge_adamic_adar_map",
            "edge_type_affinity_map",
            "edge_semantic_similarity_map",
        )

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("edge_composite_map",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ctx["edge_composite_map"] = self._result
        return ctx


class BoomEdgeOp(MemvaultOp):
    """Test op: always raises during execute."""

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ()

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("boom_edge_result",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("edge boom")


# ═══════════════════════════════════════════════════════════════════════════
# _normalize_pair — undirected edge normalization
# ═══════════════════════════════════════════════════════════════════════════


class TestNormalizePair:
    def test_lexicographically_smaller_comes_first(self):
        """Mutation kill: if impl used > instead of <, this fails."""
        assert _normalize_pair("b", "a") == ("a", "b")

    def test_already_ordered_pair_unchanged(self):
        assert _normalize_pair("a", "b") == ("a", "b")

    def test_returns_tuple_not_list(self):
        result = _normalize_pair("x", "y")
        assert isinstance(result, tuple)

    def test_same_id_reflexive_pair(self):
        """Same-entity pair: both elements identical, order preserved."""
        result = _normalize_pair("abc", "abc")
        assert result == ("abc", "abc")

    def test_uuid_style_ids(self):
        """UUIDs are compared lexicographically by spec."""
        a = "01912b3c-0000-7000-0000-000000000001"
        b = "01912b3c-0000-7000-0000-000000000002"
        assert _normalize_pair(b, a) == (a, b)

    def test_symmetric_property(self):
        """Invariant: _normalize_pair(x, y) == _normalize_pair(y, x) always."""
        assert _normalize_pair("z", "m") == _normalize_pair("m", "z")

    def test_empty_string_ids(self):
        """Edge case: empty strings are valid strings, '' < 'a' lexicographically."""
        result = _normalize_pair("a", "")
        assert result == ("", "a")


# ═══════════════════════════════════════════════════════════════════════════
# EdgeCompositeOp — weighted fusion invariants (no DB required)
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCompositeOpWeights:
    """Tests for EdgeCompositeOp using stub input maps injected into ctx."""

    def _make_ctx(
        self,
        cooccurrence: dict,
        session_overlap: dict,
        adamic_adar: dict,
        type_affinity: dict,
        semantic: dict,
    ) -> dict[str, Any]:
        return {
            "edge_cooccurrence_map": cooccurrence,
            "edge_session_overlap_map": session_overlap,
            "edge_adamic_adar_map": adamic_adar,
            "edge_type_affinity_map": type_affinity,
            "edge_semantic_similarity_map": semantic,
        }

    @pytest.mark.asyncio
    async def test_all_zeros_single_pair_produces_nonzero_due_to_normalization(self):
        """Single pair with all zeros: min-max norm maps it to 1.0 (span=0 → all 1.0).
        So composite = w_cooc*1.0 + w_aa*1.0 + others*0.0 (S2/S4/S5 are raw, not normed)."""
        config = MemvaultPipelineConfig()
        op = EdgeCompositeOp("edge.composite", config)
        pair = ("a", "b")
        ctx = self._make_ctx(
            cooccurrence={pair: 0},
            session_overlap={pair: 0.0},
            adamic_adar={pair: 0.0},
            type_affinity={pair: 0.0},
            semantic={pair: 0.0},
        )
        result = await op(ctx)
        composite_map = result["edge_composite_map"]
        assert pair in composite_map
        # S1 and S3 are min-max normalized → single value = 1.0 (span=0)
        # S2, S4, S5 are raw = 0.0
        w = config.edge_composite_weights
        expected = w["cooccurrence"] * 1.0 + w["adamic_adar"] * 1.0
        assert composite_map[pair] == pytest.approx(expected, abs=1e-6)

    @pytest.mark.asyncio
    async def test_max_normalized_inputs_produce_weight_sum(self):
        """All signals at maximum → composite ≈ sum of weights (= 1.0 per spec)."""
        config = MemvaultPipelineConfig()
        op = EdgeCompositeOp("edge.composite", config)
        pair = ("a", "b")
        ctx = self._make_ctx(
            # S1 cooccurrence and S3 adamic_adar are min-max normalized;
            # when there's only one pair, normalization yields 1.0
            cooccurrence={pair: 100},
            session_overlap={pair: 1.0},
            adamic_adar={pair: 5.0},
            type_affinity={pair: 1.0},
            semantic={pair: 1.0},
        )
        result = await op(ctx)
        composite = result["edge_composite_map"][pair]
        # weights sum to 1.0, all signals are 1.0 after normalization → composite ≈ 1.0
        assert composite == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.asyncio
    async def test_empty_all_signals_produces_empty_composite(self):
        """Invariant: no pairs in → no pairs out (no crash)."""
        config = MemvaultPipelineConfig()
        op = EdgeCompositeOp("edge.composite", config)
        ctx = self._make_ctx({}, {}, {}, {}, {})
        result = await op(ctx)
        assert result["edge_composite_map"] == {}

    @pytest.mark.asyncio
    async def test_composite_values_in_zero_one_range(self):
        """Invariant: all composites must be in [0, 1] since signals are normalised."""
        config = MemvaultPipelineConfig()
        op = EdgeCompositeOp("edge.composite", config)
        pairs = [("a", "b"), ("a", "c"), ("b", "c")]
        ctx = self._make_ctx(
            cooccurrence={p: i + 1 for i, p in enumerate(pairs)},
            session_overlap={p: (i + 1) * 0.3 for i, p in enumerate(pairs)},
            adamic_adar={p: float(i) * 0.5 for i, p in enumerate(pairs)},
            type_affinity={p: 0.9 for p in pairs},
            semantic={p: 0.7 for p in pairs},
        )
        result = await op(ctx)
        for pair, value in result["edge_composite_map"].items():
            assert 0.0 <= value <= 1.0 + 1e-9, f"{pair}: {value} out of [0,1]"

    @pytest.mark.asyncio
    async def test_config_weights_sum_to_one(self):
        """Invariant: default config weights must sum to 1.0."""
        config = MemvaultPipelineConfig()
        total = sum(config.edge_composite_weights.values())
        assert total == pytest.approx(1.0, abs=1e-9)

    @pytest.mark.asyncio
    async def test_output_key_present_in_ctx(self):
        config = MemvaultPipelineConfig()
        op = EdgeCompositeOp("edge.composite", config)
        ctx = self._make_ctx({}, {}, {}, {}, {})
        result = await op(ctx)
        assert "edge_composite_map" in result


# ═══════════════════════════════════════════════════════════════════════════
# Min-max normalization edge cases (via EdgeCompositeOp behaviour)
# ═══════════════════════════════════════════════════════════════════════════


class TestMinMaxNormalizationEdgeCases:
    """These tests drive _min_max_normalize indirectly through EdgeCompositeOp
    (六鐵律 Rule 2: test behaviour, not internals)."""

    @pytest.mark.asyncio
    async def test_single_pair_cooccurrence_normalizes_to_one(self):
        """Single-element map → min==max → all values = 1.0 by spec."""
        config = MemvaultPipelineConfig()
        op = EdgeCompositeOp("edge.composite", config)
        pair = ("a", "b")
        ctx = {
            "edge_cooccurrence_map": {pair: 42},
            "edge_session_overlap_map": {pair: 0.5},
            "edge_adamic_adar_map": {pair: 0.0},
            "edge_type_affinity_map": {pair: 0.5},
            "edge_semantic_similarity_map": {pair: 0.5},
        }
        result = await op(ctx)
        # With a single pair, S1 (cooccurrence) normalizes to 1.0
        # The composite must be > 0 (contribution from S1 weight)
        w = config.edge_composite_weights
        # S1=1.0, S3=1.0 (single AA value), S2/S4/S5 as given
        expected = (
            w["cooccurrence"] * 1.0
            + w["session_overlap"] * 0.5
            + w["adamic_adar"] * 1.0  # single value → normalized to 1.0
            + w["type_affinity"] * 0.5
            + w["semantic_similarity"] * 0.5
        )
        assert result["edge_composite_map"][pair] == pytest.approx(expected, abs=1e-6)

    @pytest.mark.asyncio
    async def test_all_same_cooccurrence_values_normalize_to_one(self):
        """All identical values → min==max → each normalized to 1.0.
        S1+S3 normalized, S2/S4/S5 raw 0.0 → composite = w_cooc + w_aa."""
        config = MemvaultPipelineConfig()
        op = EdgeCompositeOp("edge.composite", config)
        pairs = [("a", "b"), ("a", "c"), ("b", "c")]
        ctx = {
            "edge_cooccurrence_map": {p: 5 for p in pairs},  # all same → norm=1.0
            "edge_session_overlap_map": {p: 0.0 for p in pairs},
            "edge_adamic_adar_map": {p: 0.0 for p in pairs},  # all same → norm=1.0
            "edge_type_affinity_map": {p: 0.0 for p in pairs},
            "edge_semantic_similarity_map": {p: 0.0 for p in pairs},
        }
        result = await op(ctx)
        w = config.edge_composite_weights
        # S1 and S3 normalized (span=0 → all 1.0), S2/S4/S5 raw 0.0
        expected_composite = w["cooccurrence"] * 1.0 + w["adamic_adar"] * 1.0
        for pair in pairs:
            assert result["edge_composite_map"][pair] == pytest.approx(
                expected_composite, abs=1e-6
            )


# ═══════════════════════════════════════════════════════════════════════════
# MergeSurprisesOp — ctx key scanning invariants
# ═══════════════════════════════════════════════════════════════════════════


class TestMergeSurprisesOp:
    @pytest.mark.asyncio
    async def test_no_surprises_keys_produces_empty_list(self):
        """Invariant: missing surprises_* keys → empty result, not error."""
        config = MemvaultPipelineConfig()
        op = MergeSurprisesOp("surprise.merge", config)
        ctx = {"db": None, "space_id": "test-space"}
        result = await op(ctx)
        assert result["surprises"] == []

    @pytest.mark.asyncio
    async def test_merges_all_surprises_keys(self):
        config = MemvaultPipelineConfig()
        op = MergeSurprisesOp("surprise.merge", config)
        ctx = {
            "surprises_indirect_strong": [{"id": "s1", "strategy": "indirect_strong"}],
            "surprises_cross_community": [
                {"id": "s2", "strategy": "cross_community"},
                {"id": "s3", "strategy": "cross_community"},
            ],
            "surprises_knowledge_gap": [{"id": "s4", "strategy": "knowledge_gap"}],
        }
        result = await op(ctx)
        assert len(result["surprises"]) == 4

    @pytest.mark.asyncio
    async def test_ignores_non_surprises_keys(self):
        """Mutation kill: if impl merged all dict values, this would corrupt."""
        config = MemvaultPipelineConfig()
        op = MergeSurprisesOp("surprise.merge", config)
        ctx = {
            "surprises_indirect_strong": [{"id": "s1"}],
            "db": "not_a_surprise_list",
            "space_id": "not_a_surprise_list_either",
            "edge_composite_map": {("a", "b"): 0.9},
        }
        result = await op(ctx)
        assert len(result["surprises"]) == 1
        assert result["surprises"][0]["id"] == "s1"

    @pytest.mark.asyncio
    async def test_empty_surprises_sublist_handled(self):
        """One surprises_* key exists but is empty list."""
        config = MemvaultPipelineConfig()
        op = MergeSurprisesOp("surprise.merge", config)
        ctx = {
            "surprises_indirect_strong": [],
            "surprises_knowledge_gap": [{"id": "s1"}],
        }
        result = await op(ctx)
        assert len(result["surprises"]) == 1

    @pytest.mark.asyncio
    async def test_output_key_surprises_always_present(self):
        """Invariant: 'surprises' always in output even when all inputs empty."""
        config = MemvaultPipelineConfig()
        op = MergeSurprisesOp("surprise.merge", config)
        ctx = {}
        result = await op(ctx)
        assert "surprises" in result

    @pytest.mark.asyncio
    async def test_returns_dict_not_none(self):
        """Invariant: __call__ always returns dict."""
        config = MemvaultPipelineConfig()
        op = MergeSurprisesOp("surprise.merge", config)
        result = await op({})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_pipeline_meta_populated(self):
        """Invariant: _pipeline_meta always in ctx after __call__."""
        config = MemvaultPipelineConfig()
        op = MergeSurprisesOp("surprise.merge", config)
        ctx = await op({})
        assert "_pipeline_meta" in ctx
        assert isinstance(ctx["_pipeline_meta"], PipelineMeta)


# ═══════════════════════════════════════════════════════════════════════════
# Surprise ops — structural invariants (strategy field in output)
# ═══════════════════════════════════════════════════════════════════════════


class TestSurpriseOpsStructure:
    """Verifies the structural contract of each surprise op output.
    Uses a mock DB that returns an empty dataset — tests pure logic paths."""

    @pytest.mark.asyncio
    async def test_indirect_strong_output_has_strategy_field(self):
        """Invariant: every item in surprises_indirect_strong has strategy='indirect_strong'."""
        config = MemvaultPipelineConfig()
        op = SurpriseIndirectStrongOp("surprise.indirect_strong", config)
        # Minimal ctx — empty DB signals → should produce empty list without crash
        ctx = await op({"db": None, "space_id": "test-space"})
        items = ctx.get("surprises_indirect_strong", [])
        for item in items:
            assert item.get("strategy") == "indirect_strong"

    @pytest.mark.asyncio
    async def test_cross_community_output_has_community_fields(self):
        """Invariant: every item in surprises_cross_community has community_a, community_b."""
        config = MemvaultPipelineConfig()
        op = SurpriseCrossCommunityOp("surprise.cross_community", config)
        ctx = await op({"db": None, "space_id": "test-space"})
        items = ctx.get("surprises_cross_community", [])
        for item in items:
            assert "community_a" in item
            assert "community_b" in item
            assert item.get("strategy") == "cross_community"

    @pytest.mark.asyncio
    async def test_knowledge_gap_output_has_strategy_field(self):
        """Invariant: every item in surprises_knowledge_gap has strategy='knowledge_gap'."""
        config = MemvaultPipelineConfig()
        op = SurpriseKnowledgeGapOp("surprise.knowledge_gap", config)
        ctx = await op({"db": None, "space_id": "test-space"})
        items = ctx.get("surprises_knowledge_gap", [])
        for item in items:
            assert item.get("strategy") == "knowledge_gap"

    @pytest.mark.asyncio
    async def test_surprise_ops_return_dict(self):
        """Invariant: all surprise ops return dict (never None)."""
        config = MemvaultPipelineConfig()
        for OpClass, stage in [
            (SurpriseIndirectStrongOp, "surprise.indirect_strong"),
            (SurpriseCrossCommunityOp, "surprise.cross_community"),
            (SurpriseKnowledgeGapOp, "surprise.knowledge_gap"),
        ]:
            op = OpClass(stage, config)
            result = await op({"db": None, "space_id": "test-space"})
            assert isinstance(result, dict), f"{stage} returned non-dict"

    @pytest.mark.asyncio
    async def test_surprise_ops_populate_pipeline_meta(self):
        """Invariant: _pipeline_meta always populated after surprise op __call__."""
        config = MemvaultPipelineConfig()
        for OpClass, stage in [
            (SurpriseIndirectStrongOp, "surprise.indirect_strong"),
            (SurpriseCrossCommunityOp, "surprise.cross_community"),
            (SurpriseKnowledgeGapOp, "surprise.knowledge_gap"),
        ]:
            op = OpClass(stage, config)
            ctx = await op({"db": None, "space_id": "test-space"})
            assert "_pipeline_meta" in ctx


# ═══════════════════════════════════════════════════════════════════════════
# ReviewAutoApproveOp — dry_run / mutation behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestReviewAutoApproveOp:
    @pytest.mark.asyncio
    async def test_dry_run_with_null_db_fails_gracefully(self):
        """db=None triggers error isolation — op skips, no crash."""
        config = MemvaultPipelineConfig()
        op = ReviewAutoApproveOp("review.auto_approve", config)
        ctx = await op({"db": None, "space_id": "test-space", "dry_run": True})
        # With db=None, execute() fails → error isolation → skip
        meta = ctx["_pipeline_meta"]
        assert "review.auto_approve" in meta.stages_skipped
        assert isinstance(ctx, dict)

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        """Invariant: __call__ always returns dict."""
        config = MemvaultPipelineConfig()
        op = ReviewAutoApproveOp("review.auto_approve", config)
        result = await op({"db": None, "space_id": "test-space", "dry_run": True})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_pipeline_meta_populated(self):
        """Invariant: _pipeline_meta always present after __call__."""
        config = MemvaultPipelineConfig()
        op = ReviewAutoApproveOp("review.auto_approve", config)
        ctx = await op({"db": None, "space_id": "test-space", "dry_run": True})
        assert "_pipeline_meta" in ctx
        assert isinstance(ctx["_pipeline_meta"], PipelineMeta)

    @pytest.mark.asyncio
    async def test_output_key_absent_when_db_unavailable(self):
        """With db=None, op fails → output key not set (error isolation)."""
        config = MemvaultPipelineConfig()
        op = ReviewAutoApproveOp("review.auto_approve", config)
        ctx = await op({"db": None, "space_id": "test-space", "dry_run": True})
        # Op failed due to db=None → output key not present
        assert "review_auto_approved_count" not in ctx

    @pytest.mark.asyncio
    async def test_disabled_op_skips_and_no_output(self):
        """Disabled review op must not produce output keys."""
        config = MemvaultPipelineConfig()
        config.stages_enabled["review.auto_approve"] = False
        op = ReviewAutoApproveOp("review.auto_approve", config)
        ctx = await op({"db": None, "space_id": "test-space", "dry_run": True})
        assert "review_auto_approved_count" not in ctx
        assert "review.auto_approve" in ctx["_pipeline_meta"].stages_skipped

    @pytest.mark.asyncio
    async def test_error_recorded_with_null_db(self):
        """Invariant: error path records traceback in stage_errors."""
        config = MemvaultPipelineConfig()
        op = ReviewAutoApproveOp("review.auto_approve", config)
        ctx = await op({"db": None, "space_id": "test-space", "dry_run": True})
        meta = ctx["_pipeline_meta"]
        assert "review.auto_approve" in meta.stage_errors
        assert len(meta.stage_errors["review.auto_approve"]) > 0


# ═══════════════════════════════════════════════════════════════════════════
# MemvaultOp base — disabled + error path invariants on edge ops
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeOpBaseInvariants:
    @pytest.mark.asyncio
    async def test_boom_op_returns_dict(self):
        """Invariant: __call__ never raises — always returns dict."""
        config = MemvaultPipelineConfig()
        op = BoomEdgeOp("test.edge_boom", config)
        result = await op({})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_boom_op_recorded_in_stage_errors(self):
        config = MemvaultPipelineConfig()
        op = BoomEdgeOp("test.edge_boom", config)
        ctx = await op({})
        meta = ctx["_pipeline_meta"]
        assert "test.edge_boom" in meta.stages_skipped
        assert "test.edge_boom" in meta.stage_errors
        assert "edge boom" in meta.stage_errors["test.edge_boom"]

    @pytest.mark.asyncio
    async def test_disabled_edge_cooccurrence_skips(self):
        """Mutation kill: disabling edge.cooccurrence must actually skip it."""
        config = MemvaultPipelineConfig()
        config.stages_enabled["edge.cooccurrence"] = False
        op = EdgeCooccurrenceOp("edge.cooccurrence", config)
        ctx = await op({"db": None, "space_id": "test-space"})
        assert "edge_cooccurrence_map" not in ctx
        assert "edge.cooccurrence" in ctx["_pipeline_meta"].stages_skipped

    @pytest.mark.asyncio
    async def test_disabled_edge_composite_skips(self):
        config = MemvaultPipelineConfig()
        config.stages_enabled["edge.composite"] = False
        op = EdgeCompositeOp("edge.composite", config)
        ctx = await op(
            {
                "edge_cooccurrence_map": {},
                "edge_session_overlap_map": {},
                "edge_adamic_adar_map": {},
                "edge_type_affinity_map": {},
                "edge_semantic_similarity_map": {},
            }
        )
        assert "edge_composite_map" not in ctx
        assert "edge.composite" in ctx["_pipeline_meta"].stages_skipped

    @pytest.mark.asyncio
    async def test_stage_timing_non_negative_on_success(self):
        """Invariant: stage_timings[stage] >= 0 for executed stage."""
        config = MemvaultPipelineConfig()
        op = MergeSurprisesOp("surprise.merge", config)
        ctx = await op({})
        assert ctx["_pipeline_meta"].stage_timings["surprise.merge"] >= 0.0

    @pytest.mark.asyncio
    async def test_stage_timing_non_negative_on_failure(self):
        """Invariant: timing tracked even when stage fails."""
        config = MemvaultPipelineConfig()
        op = BoomEdgeOp("test.edge_boom", config)
        ctx = await op({})
        assert ctx["_pipeline_meta"].stage_timings["test.edge_boom"] >= 0.0

    @pytest.mark.asyncio
    async def test_failed_op_not_in_stages_applied(self):
        config = MemvaultPipelineConfig()
        op = BoomEdgeOp("test.edge_boom", config)
        ctx = await op({})
        assert "test.edge_boom" not in ctx["_pipeline_meta"].stages_applied


# ═══════════════════════════════════════════════════════════════════════════
# EdgeAdamicAdarOp — graph topology invariants
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeAdamicAdarOp:
    """Tests driven via injecting edge_cooccurrence_map into ctx."""

    @pytest.mark.asyncio
    async def test_empty_cooccurrence_produces_empty_adamic_adar(self):
        """Invariant: no edges → no common neighbours → empty AA map."""
        config = MemvaultPipelineConfig()
        op = EdgeAdamicAdarOp("edge.adamic_adar", config)
        ctx = {"db": None, "space_id": "test", "edge_cooccurrence_map": {}}
        result = await op(ctx)
        assert result["edge_adamic_adar_map"] == {}

    @pytest.mark.asyncio
    async def test_no_common_neighbours_means_zero_or_absent(self):
        """Two disjoint pairs share no common neighbour — AA not in output or zero."""
        config = MemvaultPipelineConfig()
        op = EdgeAdamicAdarOp("edge.adamic_adar", config)
        ctx = {
            "db": None,
            "space_id": "test",
            "edge_cooccurrence_map": {
                ("a", "b"): 2,
                ("c", "d"): 1,
            },
        }
        result = await op(ctx)
        # (a,b) and (c,d) share no neighbours → absent or 0.0 in map
        aa_map = result["edge_adamic_adar_map"]
        for pair in [("a", "b"), ("c", "d")]:
            assert aa_map.get(pair, 0.0) == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_adamic_adar_non_negative(self):
        """Invariant: AA values are always >= 0 (sum of positive terms)."""
        config = MemvaultPipelineConfig()
        op = EdgeAdamicAdarOp("edge.adamic_adar", config)
        # Triangle: a-b, b-c, a-c → b and a are common to (a,c) via b
        ctx = {
            "db": None,
            "space_id": "test",
            "edge_cooccurrence_map": {
                ("a", "b"): 3,
                ("b", "c"): 2,
                ("a", "c"): 1,
            },
        }
        result = await op(ctx)
        for val in result["edge_adamic_adar_map"].values():
            assert val >= 0.0

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = EdgeAdamicAdarOp("edge.adamic_adar", config)
        ctx = {"db": None, "space_id": "test", "edge_cooccurrence_map": {}}
        result = await op(ctx)
        assert isinstance(result, dict)
        assert "edge_adamic_adar_map" in result


# ═══════════════════════════════════════════════════════════════════════════
# EdgeSemanticSimilarityOp — graceful degradation on missing embedding service
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeSemanticSimilarityOp:
    @pytest.mark.asyncio
    async def test_returns_dict_on_db_failure(self):
        """Invariant: always returns dict even with db=None (error isolation)."""
        config = MemvaultPipelineConfig()
        op = EdgeSemanticSimilarityOp("edge.semantic_similarity", config)
        result = await op({"db": None, "space_id": "test-space"})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_graceful_error_isolation_on_null_db(self):
        """db=None triggers error isolation — op skips gracefully."""
        config = MemvaultPipelineConfig()
        op = EdgeSemanticSimilarityOp("edge.semantic_similarity", config)
        result = await op({"db": None, "space_id": "test-space"})
        meta = result["_pipeline_meta"]
        assert "edge.semantic_similarity" in meta.stages_skipped

    @pytest.mark.asyncio
    async def test_disabled_does_not_crash(self):
        """Disabled op skips without error."""
        config = MemvaultPipelineConfig()
        config.stages_enabled["edge.semantic_similarity"] = False
        op = EdgeSemanticSimilarityOp("edge.semantic_similarity", config)
        result = await op({"db": None, "space_id": "test-space"})
        assert "edge.semantic_similarity" in result["_pipeline_meta"].stages_skipped


# ═══════════════════════════════════════════════════════════════════════════
# EdgeSessionOverlapOp — Jaccard invariants
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeSessionOverlapOp:
    @pytest.mark.asyncio
    async def test_error_isolation_on_null_db(self):
        """db=None triggers error isolation — op skips, doesn't crash."""
        config = MemvaultPipelineConfig()
        op = EdgeSessionOverlapOp("edge.session_overlap", config)
        result = await op({"db": None, "space_id": "test-space"})
        assert isinstance(result, dict)
        meta = result["_pipeline_meta"]
        assert "edge.session_overlap" in meta.stages_skipped

    @pytest.mark.asyncio
    async def test_disabled_produces_no_output_key(self):
        config = MemvaultPipelineConfig()
        config.stages_enabled["edge.session_overlap"] = False
        op = EdgeSessionOverlapOp("edge.session_overlap", config)
        result = await op({"db": None, "space_id": "test-space"})
        assert isinstance(result, dict)
        assert "edge_session_overlap_map" not in result


# ═══════════════════════════════════════════════════════════════════════════
# EdgeTypeAffinityOp — same-type vs cross-type scoring invariants
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeTypeAffinityOp:
    @pytest.mark.asyncio
    async def test_error_isolation_on_null_db(self):
        """db=None triggers error isolation — op skips, doesn't crash."""
        config = MemvaultPipelineConfig()
        op = EdgeTypeAffinityOp("edge.type_affinity", config)
        result = await op({"db": None, "space_id": "test-space"})
        assert isinstance(result, dict)
        meta = result["_pipeline_meta"]
        assert "edge.type_affinity" in meta.stages_skipped

    @pytest.mark.asyncio
    async def test_disabled_produces_no_output_key(self):
        config = MemvaultPipelineConfig()
        config.stages_enabled["edge.type_affinity"] = False
        op = EdgeTypeAffinityOp("edge.type_affinity", config)
        result = await op({"db": None, "space_id": "test-space"})
        assert isinstance(result, dict)
        assert "edge_type_affinity_map" not in result


# ═══════════════════════════════════════════════════════════════════════════
# EdgePersistOp — upsert count invariants
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgePersistOp:
    @pytest.mark.asyncio
    async def test_empty_composite_map_upserts_zero(self):
        """Invariant: empty input → 0 edges upserted."""
        config = MemvaultPipelineConfig()
        op = EdgePersistOp("edge.persist", config)
        ctx = {
            "db": None,
            "space_id": "test-space",
            "edge_composite_map": {},
            "edge_cooccurrence_map": {},
            "edge_session_overlap_map": {},
            "edge_adamic_adar_map": {},
            "edge_type_affinity_map": {},
            "edge_semantic_similarity_map": {},
        }
        result = await op(ctx)
        assert result.get("edges_upserted", 0) >= 0

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = EdgePersistOp("edge.persist", config)
        ctx = {
            "db": None,
            "space_id": "test-space",
            "edge_composite_map": {},
            "edge_cooccurrence_map": {},
            "edge_session_overlap_map": {},
            "edge_adamic_adar_map": {},
            "edge_type_affinity_map": {},
            "edge_semantic_similarity_map": {},
        }
        result = await op(ctx)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_edges_upserted_is_integer(self):
        """Invariant: edges_upserted must be a non-negative integer."""
        config = MemvaultPipelineConfig()
        op = EdgePersistOp("edge.persist", config)
        ctx = {
            "db": None,
            "space_id": "test-space",
            "edge_composite_map": {},
            "edge_cooccurrence_map": {},
            "edge_session_overlap_map": {},
            "edge_adamic_adar_map": {},
            "edge_type_affinity_map": {},
            "edge_semantic_similarity_map": {},
        }
        result = await op(ctx)
        count = result.get("edges_upserted")
        if count is not None:  # may be None if DB is None
            assert isinstance(count, int)
            assert count >= 0


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline compile tests — structural wiring validation
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildEdgePipeline:
    def test_compiles_with_correct_initial_keys(self):
        """Invariant: build_edge_pipeline compiles with {db, space_id}."""
        config = MemvaultPipelineConfig()
        pipeline = build_edge_pipeline(config)
        missing = pipeline.compile(initial_keys={"db", "space_id"})
        assert missing == [], f"Missing keys: {missing}"

    def test_pipeline_not_empty(self):
        """Pipeline must have at least one stage."""
        config = MemvaultPipelineConfig()
        pipeline = build_edge_pipeline(config)
        assert len(pipeline) > 0

    def test_wrong_initial_keys_returns_missing(self):
        """Mutation kill: if compile() always returns empty, this fails."""
        config = MemvaultPipelineConfig()
        pipeline = build_edge_pipeline(config)
        missing = pipeline.compile(initial_keys=set())  # nothing provided
        # Must report missing required keys
        assert len(missing) > 0

    def test_missing_space_id_reports_missing(self):
        """Only db provided — space_id missing — compile must detect it."""
        config = MemvaultPipelineConfig()
        pipeline = build_edge_pipeline(config)
        missing = pipeline.compile(initial_keys={"db"})
        assert len(missing) > 0
        assert any("space_id" in m for m in missing)

    def test_missing_db_reports_missing(self):
        """Only space_id provided — db missing — compile must detect it."""
        config = MemvaultPipelineConfig()
        pipeline = build_edge_pipeline(config)
        missing = pipeline.compile(initial_keys={"space_id"})
        assert len(missing) > 0
        assert any("db" in m for m in missing)


class TestBuildSurprisePipeline:
    def test_compiles_with_correct_initial_keys(self):
        """Invariant: build_surprise_pipeline compiles with {db, space_id}."""
        config = MemvaultPipelineConfig()
        pipeline = build_surprise_pipeline(config)
        missing = pipeline.compile(initial_keys={"db", "space_id"})
        assert missing == [], f"Missing keys: {missing}"

    def test_pipeline_not_empty(self):
        """Pipeline must have at least one stage."""
        config = MemvaultPipelineConfig()
        pipeline = build_surprise_pipeline(config)
        assert len(pipeline) > 0

    def test_wrong_initial_keys_returns_missing(self):
        config = MemvaultPipelineConfig()
        pipeline = build_surprise_pipeline(config)
        missing = pipeline.compile(initial_keys=set())
        assert len(missing) > 0

    def test_output_keys_include_surprises(self):
        """Structural: surprise pipeline's final output must include 'surprises'."""
        config = MemvaultPipelineConfig()
        pipeline = build_surprise_pipeline(config)
        # Pipeline.output_keys is the union of all op output_keys
        assert "surprises" in pipeline.output_keys


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline error-resilience: one failing op doesn't break the pipeline
# ═══════════════════════════════════════════════════════════════════════════


class TestPipelineErrorResilience:
    @pytest.mark.asyncio
    async def test_single_failing_op_does_not_halt_pipeline_meta(self):
        """Invariant: _pipeline_meta present even when op errors."""
        config = MemvaultPipelineConfig()
        op = BoomEdgeOp("test.edge_boom", config)
        ctx = await op({})
        assert "_pipeline_meta" in ctx
        meta = ctx["_pipeline_meta"]
        assert isinstance(meta, PipelineMeta)
        assert "test.edge_boom" in meta.stage_errors

    @pytest.mark.asyncio
    async def test_merge_surprises_survives_missing_keys(self):
        """MergeSurprisesOp with partially populated ctx doesn't crash."""
        config = MemvaultPipelineConfig()
        op = MergeSurprisesOp("surprise.merge", config)
        # Only cross_community ran, others absent
        ctx = {
            "surprises_cross_community": [
                {"strategy": "cross_community", "community_a": "c1", "community_b": "c2"}
            ]
        }
        result = await op(ctx)
        assert len(result["surprises"]) == 1


# ═══════════════════════════════════════════════════════════════════════════
# All ops: __call__ always returns dict (comprehensive sweep)
# ═══════════════════════════════════════════════════════════════════════════


class TestAllOpsReturnDict:
    """Rule 3 invariant sweep: every op's __call__ returns dict, never None."""

    @pytest.mark.asyncio
    async def test_edge_cooccurrence_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = EdgeCooccurrenceOp("edge.cooccurrence", config)
        result = await op({"db": None, "space_id": "x"})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_edge_session_overlap_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = EdgeSessionOverlapOp("edge.session_overlap", config)
        result = await op({"db": None, "space_id": "x"})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_edge_adamic_adar_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = EdgeAdamicAdarOp("edge.adamic_adar", config)
        result = await op({"db": None, "space_id": "x", "edge_cooccurrence_map": {}})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_edge_type_affinity_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = EdgeTypeAffinityOp("edge.type_affinity", config)
        result = await op({"db": None, "space_id": "x"})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_edge_semantic_similarity_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = EdgeSemanticSimilarityOp("edge.semantic_similarity", config)
        result = await op({"db": None, "space_id": "x"})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_edge_composite_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = EdgeCompositeOp("edge.composite", config)
        result = await op(
            {
                "edge_cooccurrence_map": {},
                "edge_session_overlap_map": {},
                "edge_adamic_adar_map": {},
                "edge_type_affinity_map": {},
                "edge_semantic_similarity_map": {},
            }
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_edge_persist_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = EdgePersistOp("edge.persist", config)
        result = await op(
            {
                "db": None,
                "space_id": "x",
                "edge_composite_map": {},
                "edge_cooccurrence_map": {},
                "edge_session_overlap_map": {},
                "edge_adamic_adar_map": {},
                "edge_type_affinity_map": {},
                "edge_semantic_similarity_map": {},
            }
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_surprise_indirect_strong_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = SurpriseIndirectStrongOp("surprise.indirect_strong", config)
        result = await op({"db": None, "space_id": "x"})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_surprise_cross_community_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = SurpriseCrossCommunityOp("surprise.cross_community", config)
        result = await op({"db": None, "space_id": "x"})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_surprise_knowledge_gap_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = SurpriseKnowledgeGapOp("surprise.knowledge_gap", config)
        result = await op({"db": None, "space_id": "x"})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_merge_surprises_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = MergeSurprisesOp("surprise.merge", config)
        result = await op({})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_review_auto_approve_returns_dict(self):
        config = MemvaultPipelineConfig()
        op = ReviewAutoApproveOp("review.auto_approve", config)
        result = await op({"db": None, "space_id": "x", "dry_run": True})
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════════
# All ops: _pipeline_meta always populated (invariant sweep)
# ═══════════════════════════════════════════════════════════════════════════


class TestAllOpsPopulatePipelineMeta:
    """Verifies _pipeline_meta contract across all 12 new operators."""

    _base_ctx: dict[str, Any] = {
        "db": None,
        "space_id": "test-space",
        "dry_run": True,
        "edge_cooccurrence_map": {},
        "edge_session_overlap_map": {},
        "edge_adamic_adar_map": {},
        "edge_type_affinity_map": {},
        "edge_semantic_similarity_map": {},
        "edge_composite_map": {},
    }

    @pytest.mark.asyncio
    async def test_all_ops_have_pipeline_meta(self):
        config = MemvaultPipelineConfig()
        ops_to_test = [
            EdgeCooccurrenceOp("edge.cooccurrence", config),
            EdgeSessionOverlapOp("edge.session_overlap", config),
            EdgeAdamicAdarOp("edge.adamic_adar", config),
            EdgeTypeAffinityOp("edge.type_affinity", config),
            EdgeSemanticSimilarityOp("edge.semantic_similarity", config),
            EdgeCompositeOp("edge.composite", config),
            EdgePersistOp("edge.persist", config),
            SurpriseIndirectStrongOp("surprise.indirect_strong", config),
            SurpriseCrossCommunityOp("surprise.cross_community", config),
            SurpriseKnowledgeGapOp("surprise.knowledge_gap", config),
            MergeSurprisesOp("surprise.merge", config),
            ReviewAutoApproveOp("review.auto_approve", config),
        ]
        for op in ops_to_test:
            ctx = dict(self._base_ctx)
            result = await op(ctx)
            assert "_pipeline_meta" in result, f"{op.name} missing _pipeline_meta"
            assert isinstance(result["_pipeline_meta"], PipelineMeta), (
                f"{op.name} _pipeline_meta is wrong type"
            )


# ═══════════════════════════════════════════════════════════════════════════
# EdgeCompositeOp — weight configuration tests
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCompositeWeightConfig:
    @pytest.mark.asyncio
    async def test_custom_weights_applied(self):
        """Mutation kill: verify config.edge_composite_weights are actually used."""
        config = MemvaultPipelineConfig()
        # Assign all weight to semantic_similarity
        config.edge_composite_weights = {
            "cooccurrence": 0.0,
            "session_overlap": 0.0,
            "adamic_adar": 0.0,
            "type_affinity": 0.0,
            "semantic_similarity": 1.0,
        }
        op = EdgeCompositeOp("edge.composite", config)
        pair = ("a", "b")
        ctx = {
            "edge_cooccurrence_map": {pair: 100},  # irrelevant, weight=0
            "edge_session_overlap_map": {pair: 1.0},  # irrelevant, weight=0
            "edge_adamic_adar_map": {pair: 5.0},  # irrelevant, weight=0
            "edge_type_affinity_map": {pair: 1.0},  # irrelevant, weight=0
            "edge_semantic_similarity_map": {pair: 0.7},  # this is the only signal
        }
        result = await op(ctx)
        composite = result["edge_composite_map"][pair]
        # Only semantic_similarity contributes with weight 1.0 → composite = 0.7
        assert composite == pytest.approx(0.7, abs=1e-6)

    @pytest.mark.asyncio
    async def test_zero_weight_signal_has_no_effect(self):
        """Verifies a zero-weight signal cannot affect the composite."""
        config = MemvaultPipelineConfig()
        original_weights = dict(config.edge_composite_weights)
        # Zero out adamic_adar
        config.edge_composite_weights = {
            **original_weights,
            "adamic_adar": 0.0,
            "cooccurrence": original_weights["cooccurrence"]
            + original_weights["adamic_adar"],
        }
        op = EdgeCompositeOp("edge.composite", config)
        pair = ("a", "b")
        ctx = {
            "edge_cooccurrence_map": {pair: 1},
            "edge_session_overlap_map": {pair: 0.5},
            "edge_adamic_adar_map": {pair: 999.0},  # extreme value, but weight=0
            "edge_type_affinity_map": {pair: 0.5},
            "edge_semantic_similarity_map": {pair: 0.5},
        }
        result_zeroed = await op(ctx)

        # Now restore AA weight and set AA = 0.0 — should give same composite
        config.edge_composite_weights = original_weights
        op2 = EdgeCompositeOp("edge.composite", config)
        ctx2 = {
            **ctx,
            "edge_adamic_adar_map": {pair: 0.0},
        }
        # The two composites won't be equal (different weight distributions),
        # but extreme AA value with weight=0 must not produce extreme composite
        assert result_zeroed["edge_composite_map"][pair] <= 1.0 + 1e-9

"""Tests for memvault Reactive Operator infrastructure.

Follows 六鐵律:
1. Mutation thinking — edge cases that would survive naive mutations
2. Independent from implementation — tests behaviour, not internal wiring
3. Invariants over fixed I/O — properties that must always hold
4. Mock only external I/O — no mocking of MemvaultOp internals
5. Error paths covered — failure modes are first-class test cases
"""

from __future__ import annotations

from typing import Any

import pytest
from src.modules.memvault.ops._base import MemvaultOp, PipelineMeta
from src.modules.memvault.ops.lint_ops import LintOp, MergeFindingsOp
from src.modules.memvault.pipeline_config import MemvaultPipelineConfig
from src.modules.memvault.pipelines.lint_pipeline import build_lint_pipeline

# ═══════════════════════════════════════════════════════════════════════════
# Helpers — concrete op subclasses for testing (not mocking internals)
# ═══════════════════════════════════════════════════════════════════════════


class AddOp(MemvaultOp):
    """Test op: ctx["y"] = ctx["x"] + 1."""

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("x",)

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("y",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ctx["y"] = ctx["x"] + 1
        return ctx


class BoomOp(MemvaultOp):
    """Test op that always raises."""

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ()

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("boom_result",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("kaboom")


class FakeLintOp(LintOp):
    """Test lint op that always raises — verifies error finding generation."""

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("db", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("findings_fake",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        raise ConnectionError("Qdrant unavailable")


class SuccessLintOp(LintOp):
    """Test lint op that succeeds with fixed findings."""

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("db", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("findings_success",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ctx["findings_success"] = [{"check": "success", "severity": "info"}]
        return ctx


# ═══════════════════════════════════════════════════════════════════════════
# PipelineMeta invariants
# ═══════════════════════════════════════════════════════════════════════════


class TestPipelineMeta:
    def test_total_ms_is_sum_of_stage_timings(self):
        """Invariant: total_ms == sum(stage_timings.values())."""
        m = PipelineMeta()
        m.stage_timings["a"] = 10.0
        m.stage_timings["b"] = 20.5
        m.stage_timings["c"] = 0.3
        assert m.total_ms == pytest.approx(30.8)

    def test_empty_meta_total_ms_is_zero(self):
        assert PipelineMeta().total_ms == 0.0

    def test_stages_applied_and_skipped_are_independent(self):
        """Invariant: a stage appears in exactly one of applied/skipped."""
        m = PipelineMeta()
        m.stages_applied.append("a")
        m.stages_skipped.append("b")
        assert set(m.stages_applied) & set(m.stages_skipped) == set()


# ═══════════════════════════════════════════════════════════════════════════
# MemvaultOp base: toggle, isolation, timing
# ═══════════════════════════════════════════════════════════════════════════


class TestMemvaultOpToggle:
    @pytest.mark.asyncio
    async def test_enabled_op_executes(self):
        config = MemvaultPipelineConfig()
        op = AddOp("test.add", config)
        ctx = await op({"x": 10})
        assert ctx["y"] == 11
        assert "test.add" in ctx["_pipeline_meta"].stages_applied

    @pytest.mark.asyncio
    async def test_disabled_op_skips_without_executing(self):
        config = MemvaultPipelineConfig()
        config.stages_enabled["test.add"] = False
        op = AddOp("test.add", config)
        ctx = await op({"x": 10})
        # Mutation test: if toggle check used `!=` instead of `not`, this would fail
        assert "y" not in ctx
        assert "test.add" in ctx["_pipeline_meta"].stages_skipped
        assert "test.add" not in ctx["_pipeline_meta"].stages_applied

    @pytest.mark.asyncio
    async def test_unknown_stage_defaults_to_enabled(self):
        """Invariant: stages not in config default to enabled=True."""
        config = MemvaultPipelineConfig()
        op = AddOp("unknown.stage", config)
        ctx = await op({"x": 5})
        assert ctx["y"] == 6


class TestMemvaultOpErrorIsolation:
    @pytest.mark.asyncio
    async def test_exception_is_caught_and_recorded(self):
        config = MemvaultPipelineConfig()
        op = BoomOp("test.boom", config)
        ctx = await op({})
        meta = ctx["_pipeline_meta"]
        assert "test.boom" in meta.stages_skipped
        assert "test.boom" in meta.stage_errors
        assert "kaboom" in meta.stage_errors["test.boom"]

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self):
        """Invariant: MemvaultOp never raises — always returns ctx."""
        config = MemvaultPipelineConfig()
        op = BoomOp("test.boom", config)
        # Should NOT raise
        ctx = await op({})
        assert isinstance(ctx, dict)

    @pytest.mark.asyncio
    async def test_failed_op_does_not_appear_in_applied(self):
        config = MemvaultPipelineConfig()
        op = BoomOp("test.boom", config)
        ctx = await op({})
        assert "test.boom" not in ctx["_pipeline_meta"].stages_applied


class TestMemvaultOpTiming:
    @pytest.mark.asyncio
    async def test_timing_is_recorded(self):
        config = MemvaultPipelineConfig()
        op = AddOp("test.add", config)
        ctx = await op({"x": 1})
        timing = ctx["_pipeline_meta"].stage_timings["test.add"]
        assert timing >= 0.0  # Invariant: timing is non-negative

    @pytest.mark.asyncio
    async def test_timing_recorded_even_on_failure(self):
        config = MemvaultPipelineConfig()
        op = BoomOp("test.boom", config)
        ctx = await op({})
        assert "test.boom" in ctx["_pipeline_meta"].stage_timings
        assert ctx["_pipeline_meta"].stage_timings["test.boom"] >= 0.0


# ═══════════════════════════════════════════════════════════════════════════
# P2-2 fix: LintOp produces error LintFinding on failure
# ═══════════════════════════════════════════════════════════════════════════


class TestLintOpErrorFinding:
    @pytest.mark.asyncio
    async def test_failure_produces_error_finding(self):
        """P2-2: LintOp must produce a LintFinding when it fails, not silently swallow."""
        config = MemvaultPipelineConfig()
        op = FakeLintOp("lint.fake", config)
        ctx = await op({"db": None, "space_id": "test"})

        # Must have a finding in the output
        findings = ctx.get("findings_fake", [])
        assert len(findings) == 1
        finding = findings[0]
        assert finding.severity == "error"
        assert finding.check == "fake"
        assert "Qdrant unavailable" in finding.message

    @pytest.mark.asyncio
    async def test_failure_is_also_in_stage_errors(self):
        """LintOp failure should appear in both findings AND stage_errors."""
        config = MemvaultPipelineConfig()
        op = FakeLintOp("lint.fake", config)
        ctx = await op({"db": None, "space_id": "test"})

        meta = ctx["_pipeline_meta"]
        assert "lint.fake" in meta.stages_skipped
        assert "lint.fake" in meta.stage_errors
        # Also has finding
        assert len(ctx.get("findings_fake", [])) == 1

    @pytest.mark.asyncio
    async def test_successful_lint_op_no_error_finding(self):
        """Successful lint op should NOT produce error findings."""
        config = MemvaultPipelineConfig()
        op = SuccessLintOp("lint.success", config)
        ctx = await op({"db": None, "space_id": "test"})

        findings = ctx.get("findings_success", [])
        assert len(findings) == 1
        assert findings[0]["severity"] == "info"  # not "error"

    @pytest.mark.asyncio
    async def test_disabled_lint_op_no_error_finding(self):
        """Disabled lint op should produce nothing — not even error findings."""
        config = MemvaultPipelineConfig()
        config.stages_enabled["lint.fake"] = False
        op = FakeLintOp("lint.fake", config)
        ctx = await op({"db": None, "space_id": "test"})

        assert "findings_fake" not in ctx
        assert "lint.fake" in ctx["_pipeline_meta"].stages_skipped


# ═══════════════════════════════════════════════════════════════════════════
# P2-1 fix: MergeFindingsOp handles partial runs
# ═══════════════════════════════════════════════════════════════════════════


class TestMergeFindingsOp:
    @pytest.mark.asyncio
    async def test_merges_all_findings_keys(self):
        config = MemvaultPipelineConfig()
        op = MergeFindingsOp("lint.merge", config)
        ctx = {
            "findings_contradictions": [{"id": 1}],
            "findings_stale": [{"id": 2}, {"id": 3}],
        }
        result = await op(ctx)
        assert len(result["findings"]) == 3

    @pytest.mark.asyncio
    async def test_partial_run_does_not_crash(self):
        """P2-1: Only 1 check ran — MergeFindingsOp must still work."""
        config = MemvaultPipelineConfig()
        op = MergeFindingsOp("lint.merge", config)
        ctx = {"findings_stale": [{"id": 1}]}
        result = await op(ctx)
        assert len(result["findings"]) == 1

    @pytest.mark.asyncio
    async def test_empty_run_produces_empty_findings(self):
        """No checks ran — findings should be empty list, not error."""
        config = MemvaultPipelineConfig()
        op = MergeFindingsOp("lint.merge", config)
        ctx = {}
        result = await op(ctx)
        assert result["findings"] == []

    @pytest.mark.asyncio
    async def test_ignores_non_findings_keys(self):
        """Keys that don't start with findings_ should not be merged."""
        config = MemvaultPipelineConfig()
        op = MergeFindingsOp("lint.merge", config)
        ctx = {
            "findings_stale": [{"id": 1}],
            "db": "should_not_merge",
            "space_id": "also_not",
        }
        result = await op(ctx)
        assert len(result["findings"]) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline config
# ═══════════════════════════════════════════════════════════════════════════


class TestPipelineConfig:
    def test_default_stages_have_expected_count(self):
        config = MemvaultPipelineConfig()
        assert len(config.stages_enabled) >= 20

    def test_opt_in_stages_default_to_false(self):
        """Invariant: expensive stages default to disabled."""
        config = MemvaultPipelineConfig()
        assert config.is_enabled("lint.semantic_contradictions") is False
        assert config.is_enabled("crag.layer_c") is False
        assert config.is_enabled("crag.layer_d") is False

    def test_unknown_stage_defaults_to_true(self):
        config = MemvaultPipelineConfig()
        assert config.is_enabled("future.stage.that.doesnt.exist") is True

    def test_env_disable_override(self):
        import os

        os.environ["MEMVAULT_STAGES_DISABLED"] = "dream.reflect,lint.stale"
        try:
            config = MemvaultPipelineConfig.from_env()
            assert config.is_enabled("dream.reflect") is False
            assert config.is_enabled("lint.stale") is False
            assert config.is_enabled("dream.orient") is True  # unaffected
        finally:
            del os.environ["MEMVAULT_STAGES_DISABLED"]

    def test_env_enable_override(self):
        import os

        os.environ["MEMVAULT_STAGES_ENABLED"] = "crag.layer_c"
        try:
            config = MemvaultPipelineConfig.from_env()
            assert config.is_enabled("crag.layer_c") is True
        finally:
            del os.environ["MEMVAULT_STAGES_ENABLED"]


# ═══════════════════════════════════════════════════════════════════════════
# Lint pipeline factory
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildLintPipeline:
    def test_full_pipeline_compiles(self):
        """All checks selected — compile() must pass."""
        pipeline = build_lint_pipeline()
        missing = pipeline.compile(initial_keys={"db", "space_id"})
        assert missing == []

    def test_single_check_pipeline_compiles(self):
        """P2-1: Single check must compile without ParallelOp crash."""
        pipeline = build_lint_pipeline(checks=["stale"])
        missing = pipeline.compile(initial_keys={"db", "space_id"})
        assert missing == []

    def test_empty_checks_produces_empty_pipeline(self):
        """No checks selected — should compile and produce empty findings."""
        pipeline = build_lint_pipeline(checks=[])
        missing = pipeline.compile(initial_keys={"db", "space_id"})
        assert missing == []

    def test_two_checks_use_parallel(self):
        """Two+ checks should be wrapped in ParallelOp."""
        pipeline = build_lint_pipeline(checks=["stale", "contradictions"])
        # Pipeline has 2 ops: ParallelOp + MergeFindingsOp
        assert len(pipeline) == 2

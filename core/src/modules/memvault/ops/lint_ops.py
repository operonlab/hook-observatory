"""Memvault Lint Operators — thin MemvaultOp wrappers over lint.py check functions.

Each op calls one check function from ..lint and writes findings to a unique
findings_{check_name} key so ParallelOp merges don't collide.

All ops require ("db", "space_id") in ctx.
"""

from __future__ import annotations

from typing import Any

from ._base import MemvaultOp


class LintContradictionOp(MemvaultOp):
    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("db", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("findings_contradictions",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        from ..lint import check_contradictions

        results = await check_contradictions(
            ctx["db"],
            ctx["space_id"],
            sample_size=self._config.lint_contradiction_sample_size,
        )
        ctx["findings_contradictions"] = results
        return ctx


class LintStaleOp(MemvaultOp):
    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("db", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("findings_stale",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        from ..lint import check_stale_triples

        results = await check_stale_triples(
            ctx["db"],
            ctx["space_id"],
            days_threshold=self._config.lint_stale_days,
        )
        ctx["findings_stale"] = results
        return ctx


class LintOrphanOp(MemvaultOp):
    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("db", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("findings_orphan_entities",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        from ..lint import check_orphan_entities

        results = await check_orphan_entities(ctx["db"], ctx["space_id"])
        ctx["findings_orphan_entities"] = results
        return ctx


class LintDanglingRefOp(MemvaultOp):
    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("db", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("findings_dangling_refs",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        from ..lint import check_dangling_refs

        results = await check_dangling_refs(ctx["db"], ctx["space_id"])
        ctx["findings_dangling_refs"] = results
        return ctx


class LintCommunityAnomalyOp(MemvaultOp):
    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("db", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("findings_community_anomalies",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        from ..lint import check_community_anomalies

        results = await check_community_anomalies(ctx["db"], ctx["space_id"])
        ctx["findings_community_anomalies"] = results
        return ctx


class LintDataGapOp(MemvaultOp):
    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("db", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("findings_data_gaps",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        from ..lint import check_data_gaps

        results = await check_data_gaps(ctx["db"], ctx["space_id"])
        ctx["findings_data_gaps"] = results
        return ctx


class LintPredicateContradictionOp(MemvaultOp):
    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("db", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("findings_predicate_contradictions",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        from ..lint import check_predicate_contradictions

        results = await check_predicate_contradictions(ctx["db"], ctx["space_id"])
        ctx["findings_predicate_contradictions"] = results
        return ctx


class LintTemporalStalenessOp(MemvaultOp):
    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("db", "space_id")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("findings_temporal_staleness",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        from ..lint import check_temporal_staleness

        results = await check_temporal_staleness(ctx["db"], ctx["space_id"])
        ctx["findings_temporal_staleness"] = results
        return ctx


# ── Merge stage ──────────────────────────────────────────────────────────────

_FINDINGS_KEYS = (
    "findings_contradictions",
    "findings_stale",
    "findings_orphan_entities",
    "findings_dangling_refs",
    "findings_community_anomalies",
    "findings_data_gaps",
    "findings_predicate_contradictions",
    "findings_temporal_staleness",
)


class MergeFindingsOp(MemvaultOp):
    """Collect all findings_* keys into a single 'findings' list."""

    @property
    def input_keys(self) -> tuple[str, ...]:
        return _FINDINGS_KEYS

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("findings",)

    async def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        merged: list = []
        for key in _FINDINGS_KEYS:
            merged.extend(ctx.get(key) or [])
        ctx["findings"] = merged
        return ctx

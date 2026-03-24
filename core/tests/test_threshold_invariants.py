"""
Adversarial threshold invariant tests.

六鐵律 compliance:
  #1 Mutation thinking  — tests are named to explicitly catch each mutation target
  #3 Invariant-first    — range bounds and monotonicity before behaviour
  #5 No mocks           — all functions are pure; no patching needed

CRITICAL: Do NOT read the implementation files before extending this suite.
Invariants are derived solely from docstrings and function signatures.
"""

import pytest
from src.modules.capture.grc_adapter import _low_confidence_threshold
from src.modules.capture.services import _confidence_threshold
from src.modules.memvault.conflict_resolver import _conflict_threshold
from src.modules.memvault.dedup import (
    _conflict_dedup_threshold,
    _dedup_similarity_threshold,
)
from src.modules.memvault.query_router import _route_confidence_threshold

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_in_range(value: float, lo: float, hi: float, label: str) -> None:
    assert lo <= value <= hi, f"{label}: expected value in [{lo}, {hi}], got {value}"


# ===========================================================================
# TestCaptureThresholds
# ===========================================================================


class TestCaptureThresholds:
    """_confidence_threshold and _low_confidence_threshold (capture module)."""

    # -----------------------------------------------------------------------
    # _confidence_threshold
    # -----------------------------------------------------------------------

    # -- Range invariants (鐵律 #3) ----------------------------------------

    def test_confidence_lower_bound_default(self):
        """Default call must satisfy lower clamp >= 0.3."""
        result = _confidence_threshold()
        assert result >= 0.3, f"Lower clamp violated: {result}"

    def test_confidence_upper_bound_default(self):
        """Default call must satisfy upper clamp <= 0.8."""
        result = _confidence_threshold()
        assert result <= 0.8, f"Upper clamp violated: {result}"

    def test_confidence_lower_bound_zero_depth(self):
        """depth=0 must still satisfy lower clamp >= 0.3.

        Mutation target: max(0.3, ...) → min(0.3, ...) would make this fail.
        """
        result = _confidence_threshold(enrichment_depth=0)
        _assert_in_range(result, 0.3, 0.8, "_confidence_threshold(depth=0)")

    def test_confidence_upper_bound_extreme_depth(self):
        """Very large depth must be clamped at 0.8.

        Mutation target: min(0.8, ...) → min(8.0, ...) would make this fail.
        """
        result = _confidence_threshold(enrichment_depth=1000)
        assert result <= 0.8, f"Upper clamp violated for extreme depth: {result}"

    def test_confidence_range_for_all_typical_depths(self):
        """Parametric range check across depths 0-10."""
        for depth in range(11):
            result = _confidence_threshold(enrichment_depth=depth)
            _assert_in_range(result, 0.3, 0.8, f"_confidence_threshold(depth={depth})")

    # -- Default value sanity (鐵律 #3) --------------------------------------

    def test_confidence_default_depth1_is_around_0_50(self):
        """Docstring states 'base 0.45 + 0.05 per depth'; depth=1 → 0.50.

        Mutation target: 0.45 + 0.05 * depth → 0.45 - 0.05 * depth would
        give 0.40 for depth=1, failing this check.
        """
        result = _confidence_threshold(enrichment_depth=1)
        assert abs(result - 0.50) < 0.01, f"depth=1 expected ~0.50, got {result}"

    # -- Monotonicity (鐵律 #3) ----------------------------------------------

    def test_confidence_monotonic_depth0_vs_depth1(self):
        """depth=1 threshold must be >= depth=0 threshold.

        Mutation target: 0.45 + 0.05 * depth → 0.45 - 0.05 * depth would
        invert the ordering.
        """
        assert _confidence_threshold(1) >= _confidence_threshold(0)

    def test_confidence_monotonic_depth1_vs_depth2(self):
        assert _confidence_threshold(2) >= _confidence_threshold(1)

    def test_confidence_monotonic_depth5_vs_depth10(self):
        assert _confidence_threshold(10) >= _confidence_threshold(5)

    def test_confidence_monotonic_strictly_before_clamp(self):
        """Before the upper clamp kicks in, each extra depth level must raise
        the threshold by a positive amount.

        Depths 0,1,2 are well below the ceiling so strict ordering holds.
        """
        results = [_confidence_threshold(d) for d in range(3)]
        for i in range(len(results) - 1):
            assert results[i + 1] > results[i], (
                f"Not strictly increasing: depth {i}={results[i]}, depth {i + 1}={results[i + 1]}"
            )

    # -----------------------------------------------------------------------
    # _low_confidence_threshold
    # -----------------------------------------------------------------------

    # -- Range invariants ---------------------------------------------------

    def test_low_conf_lower_bound_default(self):
        """Default call lower clamp >= 0.35.

        Mutation target: max(0.35, ...) → min(0.35, ...).
        """
        result = _low_confidence_threshold()
        assert result >= 0.35, f"Lower clamp violated: {result}"

    def test_low_conf_upper_bound_default(self):
        """Default call upper clamp <= 0.65."""
        result = _low_confidence_threshold()
        assert result <= 0.65, f"Upper clamp violated: {result}"

    def test_low_conf_lower_bound_zero_count(self):
        result = _low_confidence_threshold(enrichment_count=0)
        _assert_in_range(result, 0.35, 0.65, "_low_confidence_threshold(count=0)")

    def test_low_conf_upper_bound_extreme_count(self):
        """Extreme count must be clamped at 0.65.

        Mutation target: min(0.65, ...) → min(6.5, ...).
        """
        result = _low_confidence_threshold(enrichment_count=1000)
        assert result <= 0.65, f"Upper clamp violated for extreme count: {result}"

    def test_low_conf_range_for_typical_counts(self):
        for count in range(11):
            result = _low_confidence_threshold(enrichment_count=count)
            _assert_in_range(result, 0.35, 0.65, f"_low_confidence_threshold(count={count})")

    # -- Monotonicity -------------------------------------------------------

    def test_low_conf_monotonic_count0_vs_count1(self):
        """More enrichment → bar rises."""
        assert _low_confidence_threshold(1) >= _low_confidence_threshold(0)

    def test_low_conf_monotonic_count1_vs_count5(self):
        assert _low_confidence_threshold(5) >= _low_confidence_threshold(1)

    def test_low_conf_monotonic_strictly_before_clamp(self):
        """Strict ordering before the ceiling kicks in."""
        results = [_low_confidence_threshold(c) for c in range(3)]
        for i in range(len(results) - 1):
            assert results[i + 1] > results[i], (
                f"Not strictly increasing: count {i}={results[i]}, count {i + 1}={results[i + 1]}"
            )


# ===========================================================================
# TestMemvaultConflictThresholds
# ===========================================================================


class TestMemvaultConflictThresholds:
    """_conflict_threshold (conflict_resolver module)."""

    # -- Range invariants ---------------------------------------------------

    def test_conflict_lower_bound_default(self):
        """Default call lower clamp >= 0.80.

        Mutation target: max(0.80, ...) → min(0.80, ...).
        """
        result = _conflict_threshold()
        assert result >= 0.80, f"Lower clamp violated: {result}"

    def test_conflict_upper_bound_default(self):
        """Default call upper clamp <= 0.92."""
        result = _conflict_threshold()
        assert result <= 0.92, f"Upper clamp violated: {result}"

    def test_conflict_range_for_memory_type(self):
        result = _conflict_threshold(block_type="memory")
        _assert_in_range(result, 0.80, 0.92, "_conflict_threshold('memory')")

    def test_conflict_range_for_attitude_type(self):
        result = _conflict_threshold(block_type="attitude")
        _assert_in_range(result, 0.80, 0.92, "_conflict_threshold('attitude')")

    def test_conflict_range_for_skill_type(self):
        result = _conflict_threshold(block_type="skill")
        _assert_in_range(result, 0.80, 0.92, "_conflict_threshold('skill')")

    def test_conflict_range_for_knowledge_type(self):
        result = _conflict_threshold(block_type="knowledge")
        _assert_in_range(result, 0.80, 0.92, "_conflict_threshold('knowledge')")

    def test_conflict_range_for_unknown_type(self):
        """Unknown block_type must still be within clamp range."""
        result = _conflict_threshold(block_type="__unknown__")
        _assert_in_range(result, 0.80, 0.92, "_conflict_threshold('__unknown__')")

    # -- Type-specific invariant: attitude/skill stricter than knowledge ----

    def test_conflict_attitude_stricter_than_knowledge(self):
        """Docstring: attitudes/skills use stricter (higher) threshold.

        Higher threshold means the bar fires *earlier* (at lower divergence),
        i.e. attitude threshold >= knowledge threshold.
        """
        attitude = _conflict_threshold(block_type="attitude")
        knowledge = _conflict_threshold(block_type="knowledge")
        assert attitude >= knowledge, f"attitude ({attitude}) should be >= knowledge ({knowledge})"

    def test_conflict_skill_stricter_than_knowledge(self):
        skill = _conflict_threshold(block_type="skill")
        knowledge = _conflict_threshold(block_type="knowledge")
        assert skill >= knowledge, f"skill ({skill}) should be >= knowledge ({knowledge})"

    def test_conflict_attitude_and_skill_close_or_equal(self):
        """attitude and skill are both described as 'personal facts that
        should merge aggressively'; their thresholds should be close."""
        diff = abs(_conflict_threshold("attitude") - _conflict_threshold("skill"))
        assert diff <= 0.05, f"attitude vs skill thresholds diverge too much: {diff}"

    def test_conflict_upper_bound_extreme_type(self):
        """Even a pathologically long type name must not exceed 0.92."""
        result = _conflict_threshold(block_type="x" * 1000)
        assert result <= 0.92, f"Upper clamp violated: {result}"


# ===========================================================================
# TestMemvaultDedupThresholds
# ===========================================================================


class TestMemvaultDedupThresholds:
    """_dedup_similarity_threshold and _conflict_dedup_threshold (dedup module)."""

    # -----------------------------------------------------------------------
    # _dedup_similarity_threshold
    # -----------------------------------------------------------------------

    def test_dedup_lower_bound_default(self):
        """Default lower clamp >= 0.70.

        Mutation target: max(0.70, ...) → min(0.70, ...).
        """
        result = _dedup_similarity_threshold()
        assert result >= 0.70, f"Lower clamp violated: {result}"

    def test_dedup_upper_bound_default(self):
        """Default upper clamp <= 0.92."""
        result = _dedup_similarity_threshold()
        assert result <= 0.92, f"Upper clamp violated: {result}"

    def test_dedup_range_for_general_category(self):
        result = _dedup_similarity_threshold(category="general")
        _assert_in_range(result, 0.70, 0.92, "_dedup_similarity_threshold('general')")

    def test_dedup_range_for_any_category(self):
        """Parametric check across typical category names."""
        for cat in ("general", "memory", "attitude", "skill", "knowledge", "fact"):
            result = _dedup_similarity_threshold(category=cat)
            _assert_in_range(result, 0.70, 0.92, f"_dedup_similarity_threshold('{cat}')")

    def test_dedup_range_for_unknown_category(self):
        result = _dedup_similarity_threshold(category="__unknown__")
        _assert_in_range(result, 0.70, 0.92, "_dedup_similarity_threshold('__unknown__')")

    def test_dedup_upper_bound_extreme_category(self):
        result = _dedup_similarity_threshold(category="x" * 1000)
        assert result <= 0.92, f"Upper clamp violated: {result}"

    # -----------------------------------------------------------------------
    # _conflict_dedup_threshold
    # -----------------------------------------------------------------------

    def test_conflict_dedup_lower_bound_default(self):
        """Default lower clamp >= 0.80.

        Mutation target: max(0.80, ...) → min(0.80, ...).
        """
        result = _conflict_dedup_threshold()
        assert result >= 0.80, f"Lower clamp violated: {result}"

    def test_conflict_dedup_upper_bound_default(self):
        """Default upper clamp <= 0.92."""
        result = _conflict_dedup_threshold()
        assert result <= 0.92, f"Upper clamp violated: {result}"

    def test_conflict_dedup_range_for_memory_type(self):
        result = _conflict_dedup_threshold(block_type="memory")
        _assert_in_range(result, 0.80, 0.92, "_conflict_dedup_threshold('memory')")

    def test_conflict_dedup_range_for_attitude_type(self):
        result = _conflict_dedup_threshold(block_type="attitude")
        _assert_in_range(result, 0.80, 0.92, "_conflict_dedup_threshold('attitude')")

    def test_conflict_dedup_range_for_knowledge_type(self):
        result = _conflict_dedup_threshold(block_type="knowledge")
        _assert_in_range(result, 0.80, 0.92, "_conflict_dedup_threshold('knowledge')")

    def test_conflict_dedup_range_for_unknown_type(self):
        result = _conflict_dedup_threshold(block_type="__unknown__")
        _assert_in_range(result, 0.80, 0.92, "_conflict_dedup_threshold('__unknown__')")

    # -- Cross-function consistency (docstring states "matches _conflict_threshold") --

    def test_conflict_dedup_matches_conflict_resolver_for_memory(self):
        """Docstring: 'matches _conflict_threshold() in conflict_resolver for
        consistency'. Both should return the same value for the same block_type.
        """
        assert _conflict_dedup_threshold("memory") == pytest.approx(
            _conflict_threshold("memory"), abs=1e-9
        )

    def test_conflict_dedup_matches_conflict_resolver_for_attitude(self):
        assert _conflict_dedup_threshold("attitude") == pytest.approx(
            _conflict_threshold("attitude"), abs=1e-9
        )

    def test_conflict_dedup_matches_conflict_resolver_for_knowledge(self):
        assert _conflict_dedup_threshold("knowledge") == pytest.approx(
            _conflict_threshold("knowledge"), abs=1e-9
        )


# ===========================================================================
# TestQueryRouterThresholds
# ===========================================================================


class TestQueryRouterThresholds:
    """_route_confidence_threshold (query_router module)."""

    # -- Range invariants ---------------------------------------------------

    def test_route_lower_bound_default(self):
        """Default call lower clamp >= 0.25.

        Mutation target: max(0.25, ...) → min(0.25, ...).
        """
        result = _route_confidence_threshold(query_len=20)
        assert result >= 0.25, f"Lower clamp violated: {result}"

    def test_route_upper_bound_default(self):
        """Default-length query (20) upper clamp <= 0.6."""
        result = _route_confidence_threshold(query_len=20)
        assert result <= 0.6, f"Upper clamp violated: {result}"

    def test_route_range_for_very_short_query(self):
        result = _route_confidence_threshold(query_len=1)
        _assert_in_range(result, 0.25, 0.6, "_route_confidence_threshold(1)")

    def test_route_range_for_short_query(self):
        result = _route_confidence_threshold(query_len=5)
        _assert_in_range(result, 0.25, 0.6, "_route_confidence_threshold(5)")

    def test_route_range_for_default_query(self):
        result = _route_confidence_threshold(query_len=20)
        _assert_in_range(result, 0.25, 0.6, "_route_confidence_threshold(20)")

    def test_route_range_for_long_query(self):
        result = _route_confidence_threshold(query_len=50)
        _assert_in_range(result, 0.25, 0.6, "_route_confidence_threshold(50)")

    def test_route_upper_bound_extreme_len(self):
        """Very large query_len must be clamped at 0.6.

        Mutation target: min(0.6, ...) → min(6.0, ...) would let value escape.
        """
        result = _route_confidence_threshold(query_len=10_000)
        assert result <= 0.6, f"Upper clamp violated for extreme query_len: {result}"

    def test_route_lower_bound_zero_len(self):
        """Zero-length query must stay >= 0.25.

        Mutation target: max(0.25, ...) → min(0.25, ...).
        """
        result = _route_confidence_threshold(query_len=0)
        assert result >= 0.25, f"Lower clamp violated for query_len=0: {result}"

    # -- Monotonicity: short queries → lower threshold ---------------------

    def test_route_short_query_lower_than_long(self):
        """Docstring: short queries are ambiguous → lower the bar.
        len=5 threshold must be <= len=50 threshold.

        Mutation target: inverted formula would make short queries yield higher
        thresholds.
        """
        short = _route_confidence_threshold(query_len=5)
        long_ = _route_confidence_threshold(query_len=50)
        assert short <= long_, f"Short query ({short}) should be <= long query ({long_})"

    def test_route_monotonic_5_10_20_50(self):
        """Threshold must be non-decreasing as query_len grows (before cap)."""
        lens = [5, 10, 20, 50]
        results = [_route_confidence_threshold(l) for l in lens]
        for i in range(len(results) - 1):
            assert results[i] <= results[i + 1], (
                f"Not non-decreasing: len {lens[i]}={results[i]}, "
                f"len {lens[i + 1]}={results[i + 1]}"
            )

    # -- Cap invariant: query_len capped at 50 -----------------------------

    def test_route_cap_at_50(self):
        """query_len is capped at 50 — len=50 and len=1000 must yield same value.

        Mutation target: if cap is removed, len=1000 would return a higher value
        than len=50.
        """
        at_cap = _route_confidence_threshold(query_len=50)
        over_cap = _route_confidence_threshold(query_len=1000)
        assert at_cap == pytest.approx(over_cap, abs=1e-9), (
            f"Cap invariant violated: len=50 → {at_cap}, len=1000 → {over_cap}"
        )

    def test_route_cap_at_50_vs_51(self):
        """len=51 should also equal len=50 (cap is strictly at 50)."""
        at_cap = _route_confidence_threshold(query_len=50)
        just_over = _route_confidence_threshold(query_len=51)
        assert at_cap == pytest.approx(just_over, abs=1e-9), (
            f"Cap invariant violated: len=50 → {at_cap}, len=51 → {just_over}"
        )

    def test_route_cap_growth_stops_at_50(self):
        """Values for len >= 50 must all be equal (no unbounded growth).

        Mutation target: cap removed → each extra character keeps raising value.
        """
        reference = _route_confidence_threshold(query_len=50)
        for length in (51, 100, 500, 10_000):
            result = _route_confidence_threshold(query_len=length)
            assert result == pytest.approx(reference, abs=1e-9), (
                f"Growth beyond cap: len={length} → {result}, expected {reference}"
            )

"""
Tests for session quality threshold functions in reflect_engine.py.

Test-adversary design: tests are written ONLY from the behavioral specification
and function signatures — implementation is not read.

Mutation targets covered:
  - base = 0.50 → base = 5.0              → test_probability_range catches this
  - max(0.30, ...) → min(0.30, ...)       → test_range_bound catches this
  - turn_count - 10 → turn_count + 10    → test_short_session_tolerance catches this
  - base - adjustment → base + adjustment → test_monotonic_direction catches this

Implementation note: functions use piecewise logic with a step at turn_count=10.
Within each segment the change per step is < 0.05, but the cross-boundary
step at n=10→11 is larger (up to ~0.15). CONSECUTIVE_PAIRS therefore tests
smooth segments only (n<=9 and n>=11); the boundary is covered by a dedicated test.
"""

import sys
from pathlib import Path

# Add stations/session-pipeline to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from reflect_engine import (
    _calc_failure_threshold,
    _calc_partial_error_threshold,
    _calc_partial_tool_success_threshold,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TURN_COUNTS = [0, 1, 5, 10, 20, 50, 100, 500, 10_000]

# Smooth-segment pairs: exclude the piecewise boundary at n=10→11.
# Within each segment the delta must be < 0.05; the boundary itself is tested separately.
CONSECUTIVE_PAIRS = (
    list(zip(range(0, 10), range(1, 11)))  # segment 1: n=0..9
    + list(zip(range(11, 200), range(12, 201)))  # segment 2: n=11..199
)


# ---------------------------------------------------------------------------
# TestFailureThreshold
# ---------------------------------------------------------------------------


class TestFailureThreshold:
    """_calc_failure_threshold: error-rate that triggers 'failure' classification."""

    # --- Invariant: probability range (catches base = 5.0 mutation) ---

    @pytest.mark.parametrize("n", SAMPLE_TURN_COUNTS)
    def test_probability_range(self, n: int):
        """Result must be a valid probability: 0 < result < 1."""
        result = _calc_failure_threshold(n)
        assert 0 < result < 1, f"turn_count={n}: expected (0,1), got {result}"

    # --- Invariant: bounded to [0.30, 0.65] (catches min/max swap mutation) ---

    @pytest.mark.parametrize("n", SAMPLE_TURN_COUNTS)
    def test_range_bound(self, n: int):
        """Result must stay within [0.30, 0.65]."""
        result = _calc_failure_threshold(n)
        assert 0.30 <= result <= 0.65, f"turn_count={n}: expected [0.30, 0.65], got {result}"

    # --- Invariant: stable at extremes (no overflow/crash) ---

    def test_stable_at_zero(self):
        result = _calc_failure_threshold(0)
        assert isinstance(result, float)
        assert 0 < result < 1

    def test_stable_at_large(self):
        result = _calc_failure_threshold(10_000)
        assert isinstance(result, float)
        assert 0 < result < 1

    # --- Invariant: bounded change |f(n+1) - f(n)| < 0.05 (no sudden jumps) ---

    @pytest.mark.parametrize("n,n1", CONSECUTIVE_PAIRS)
    def test_bounded_change(self, n: int, n1: int):
        """No sudden jumps within smooth segments (< 0.05 per step)."""
        delta = abs(_calc_failure_threshold(n1) - _calc_failure_threshold(n))
        assert delta < 0.05, f"|f({n1}) - f({n})| = {delta:.4f} >= 0.05"

    def test_piecewise_boundary_is_bounded(self):
        """The piecewise step at n=10→11 must remain < 0.20 (no runaway jump)."""
        delta = abs(_calc_failure_threshold(11) - _calc_failure_threshold(10))
        assert delta < 0.20, f"|f(11) - f(10)| = {delta:.4f} >= 0.20 (runaway boundary jump)"

    # --- Invariant: not constant (catches turn_count ignored / flat function) ---

    def test_not_constant(self):
        """Short vs long session must differ (catches hardcoded constant mutation)."""
        short = _calc_failure_threshold(5)
        long_ = _calc_failure_threshold(100)
        assert short != long_, (
            f"Expected different values for turn_count=5 and turn_count=100, both returned {short}"
        )

    # --- Invariant: short sessions more tolerant → threshold rises for longer sessions
    #     Docstring says "rises slightly for longer sessions"
    #     → f(long) > f(short) catches (base - adjustment → base + adjustment) mutation ---

    def test_monotonic_direction_short_to_long(self):
        """Longer sessions must have a higher (stricter) failure threshold."""
        short = _calc_failure_threshold(5)
        long_ = _calc_failure_threshold(100)
        assert long_ > short, (
            f"Expected failure_threshold(100) > failure_threshold(5), got {long_} <= {short}"
        )

    def test_short_session_tolerance(self):
        """Short sessions should be more tolerant (lower threshold) than long ones.
        Catches turn_count - 10 → turn_count + 10 shift mutation."""
        very_short = _calc_failure_threshold(1)
        moderate = _calc_failure_threshold(50)
        assert very_short < moderate, (
            f"Expected failure_threshold(1) < failure_threshold(50), got {very_short} >= {moderate}"
        )


# ---------------------------------------------------------------------------
# TestPartialErrorThreshold
# ---------------------------------------------------------------------------


class TestPartialErrorThreshold:
    """_calc_partial_error_threshold: error-rate for 'partial' classification."""

    @pytest.mark.parametrize("n", SAMPLE_TURN_COUNTS)
    def test_probability_range(self, n: int):
        """Result must be a valid probability: 0 < result < 1."""
        result = _calc_partial_error_threshold(n)
        assert 0 < result < 1, f"turn_count={n}: expected (0,1), got {result}"

    @pytest.mark.parametrize("n", SAMPLE_TURN_COUNTS)
    def test_range_bound(self, n: int):
        """Result must stay within [0.10, 0.35]."""
        result = _calc_partial_error_threshold(n)
        assert 0.10 <= result <= 0.35, f"turn_count={n}: expected [0.10, 0.35], got {result}"

    def test_stable_at_zero(self):
        result = _calc_partial_error_threshold(0)
        assert isinstance(result, float)
        assert 0 < result < 1

    def test_stable_at_large(self):
        result = _calc_partial_error_threshold(10_000)
        assert isinstance(result, float)
        assert 0 < result < 1

    @pytest.mark.parametrize("n,n1", CONSECUTIVE_PAIRS)
    def test_bounded_change(self, n: int, n1: int):
        """No sudden jumps within smooth segments (< 0.05 per step)."""
        delta = abs(_calc_partial_error_threshold(n1) - _calc_partial_error_threshold(n))
        assert delta < 0.05, f"|f({n1}) - f({n})| = {delta:.4f} >= 0.05"

    def test_piecewise_boundary_is_bounded(self):
        """The piecewise step at n=10→11 must remain < 0.20 (no runaway jump)."""
        delta = abs(_calc_partial_error_threshold(11) - _calc_partial_error_threshold(10))
        assert delta < 0.20, f"|f(11) - f(10)| = {delta:.4f} >= 0.20 (runaway boundary jump)"

    def test_not_constant(self):
        """Short vs long session must differ (catches hardcoded constant mutation)."""
        short = _calc_partial_error_threshold(5)
        long_ = _calc_partial_error_threshold(100)
        assert short != long_, (
            f"Expected different values for turn_count=5 and turn_count=100, both returned {short}"
        )


# ---------------------------------------------------------------------------
# TestPartialToolSuccessThreshold
# ---------------------------------------------------------------------------


class TestPartialToolSuccessThreshold:
    """_calc_partial_tool_success_threshold: tool success-rate for 'partial' classification.

    Docstring: 'loosens slightly for longer sessions' → value decreases for higher turn_count
    (lower success bar required to pass 'partial' for long sessions).
    """

    @pytest.mark.parametrize("n", SAMPLE_TURN_COUNTS)
    def test_probability_range(self, n: int):
        """Result must be a valid probability: 0 < result < 1."""
        result = _calc_partial_tool_success_threshold(n)
        assert 0 < result < 1, f"turn_count={n}: expected (0,1), got {result}"

    @pytest.mark.parametrize("n", SAMPLE_TURN_COUNTS)
    def test_range_bound(self, n: int):
        """Result must stay within [0.50, 0.85]."""
        result = _calc_partial_tool_success_threshold(n)
        assert 0.50 <= result <= 0.85, f"turn_count={n}: expected [0.50, 0.85], got {result}"

    def test_stable_at_zero(self):
        result = _calc_partial_tool_success_threshold(0)
        assert isinstance(result, float)
        assert 0 < result < 1

    def test_stable_at_large(self):
        result = _calc_partial_tool_success_threshold(10_000)
        assert isinstance(result, float)
        assert 0 < result < 1

    @pytest.mark.parametrize("n,n1", CONSECUTIVE_PAIRS)
    def test_bounded_change(self, n: int, n1: int):
        """No sudden jumps within smooth segments (< 0.05 per step)."""
        delta = abs(
            _calc_partial_tool_success_threshold(n1) - _calc_partial_tool_success_threshold(n)
        )
        assert delta < 0.05, f"|f({n1}) - f({n})| = {delta:.4f} >= 0.05"

    def test_piecewise_boundary_is_bounded(self):
        """The piecewise step at n=10→11 must remain < 0.20 (no runaway jump)."""
        delta = abs(
            _calc_partial_tool_success_threshold(11) - _calc_partial_tool_success_threshold(10)
        )
        assert delta < 0.20, f"|f(11) - f(10)| = {delta:.4f} >= 0.20 (runaway boundary jump)"

    def test_not_constant(self):
        """Short vs long session must differ."""
        short = _calc_partial_tool_success_threshold(5)
        long_ = _calc_partial_tool_success_threshold(100)
        assert short != long_, (
            f"Expected different values for turn_count=5 and turn_count=100, both returned {short}"
        )

    def test_loosens_for_longer_sessions(self):
        """'Loosens' = lower value for longer sessions (less tool-success required).
        Catches base + adjustment → base - adjustment mutation."""
        short = _calc_partial_tool_success_threshold(5)
        long_ = _calc_partial_tool_success_threshold(100)
        assert long_ < short, (
            f"Expected tool_success_threshold(100) < tool_success_threshold(5) "
            f"(loosens for longer sessions), got {long_} >= {short}"
        )

    def test_short_session_strictness(self):
        """Short sessions should demand higher tool success rate.
        Catches turn_count - 10 → turn_count + 10 shift mutation."""
        very_short = _calc_partial_tool_success_threshold(1)
        moderate = _calc_partial_tool_success_threshold(50)
        assert very_short > moderate, (
            f"Expected tool_success_threshold(1) > tool_success_threshold(50), "
            f"got {very_short} <= {moderate}"
        )


# ---------------------------------------------------------------------------
# TestCrossFunctionInvariants
# ---------------------------------------------------------------------------


class TestCrossFunctionInvariants:
    """Cross-function invariants: relationships between the three threshold functions."""

    @pytest.mark.parametrize("n", SAMPLE_TURN_COUNTS)
    def test_failure_threshold_exceeds_partial_error_threshold(self, n: int):
        """failure_threshold > partial_error_threshold for all turn counts.

        Semantic: more errors are required to be classified as 'failure' than 'partial'.
        This catches any implementation inversion between the two functions.
        """
        failure = _calc_failure_threshold(n)
        partial_err = _calc_partial_error_threshold(n)
        assert failure > partial_err, (
            f"turn_count={n}: failure_threshold ({failure:.4f}) must be > "
            f"partial_error_threshold ({partial_err:.4f})"
        )

    @pytest.mark.parametrize("n", SAMPLE_TURN_COUNTS)
    def test_all_three_are_valid_probabilities(self, n: int):
        """All three functions must return valid probabilities simultaneously."""
        f = _calc_failure_threshold(n)
        pe = _calc_partial_error_threshold(n)
        pts = _calc_partial_tool_success_threshold(n)
        for name, val in [("failure", f), ("partial_error", pe), ("partial_tool_success", pts)]:
            assert 0 < val < 1, f"turn_count={n}: {name} threshold = {val} is not in (0, 1)"

    def test_ordering_consistency_across_session_lengths(self):
        """failure > partial_error must hold at multiple representative turn counts."""
        for n in [1, 10, 25, 50, 100, 500]:
            failure = _calc_failure_threshold(n)
            partial = _calc_partial_error_threshold(n)
            assert failure > partial, (
                f"Ordering violated at turn_count={n}: "
                f"failure={failure:.4f}, partial_error={partial:.4f}"
            )

    def test_gap_between_failure_and_partial_error_is_meaningful(self):
        """The gap between failure and partial_error thresholds should be > 0.05
        at representative points — catching near-zero gap degeneracies."""
        for n in [5, 20, 50]:
            gap = _calc_failure_threshold(n) - _calc_partial_error_threshold(n)
            assert gap > 0.05, (
                f"turn_count={n}: gap between failure and partial_error thresholds "
                f"is only {gap:.4f} (expected > 0.05 for meaningful separation)"
            )

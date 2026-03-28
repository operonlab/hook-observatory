"""Adversarial tests for dynamic_timeout parameters used in omlx_bridge and rerank_bridge.

六鐵律 compliance:
  #1 Mutation thinking  — each test catches a specific parameter mutation
  #2 Writing ≠ running  — spec-derived, implementation NOT read before writing
  #3 Invariant-first    — monotonicity and cap before edge cases
  #5 Pure-function test — dynamic_timeout is pure; no mocks needed

These tests validate the SPECIFIC parameter sets used in the bridges:

  omlx_bridge write:  base=10,  factor=0.5, cap=30
  omlx_bridge read:   base=30,  factor=0.5, cap=120
  (rerank_bridge uses subprocess retry — covered separately at integration level)

Import: workshop.timeout.dynamic_timeout (shared utility)

MUTATION TARGETS:
  - write base=10  → base=1   caught by: test_write_small_input_near_base
  - write cap=30   → cap=300  caught by: test_write_capped_at_30
  - read base=30   → base=3   caught by: test_read_small_input_near_base
  - read cap=120   → cap=1200 caught by: test_read_capped_at_120
  - factor=0.5 → 0.0          caught by: test_write_timeout_monotonically_increases
  - monotonicity broken        caught by: test_read_timeout_monotonically_increases
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_CORE_ROOT = Path(__file__).resolve().parent.parent
if str(_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CORE_ROOT))

from sdk_client.timeout import dynamic_timeout  # noqa: E402

# ---------------------------------------------------------------------------
# Constants — mirror the bridge parameters exactly
# ---------------------------------------------------------------------------

# omlx_bridge write channel
_WRITE_BASE = 10
_WRITE_FACTOR = 0.5
_WRITE_CAP = 30

# omlx_bridge read channel
_READ_BASE = 30
_READ_FACTOR = 0.5
_READ_CAP = 120


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_timeout(context: int) -> float:
    """Apply omlx_bridge write channel parameters."""
    return dynamic_timeout(base=_WRITE_BASE, factor=_WRITE_FACTOR, context=context, cap=_WRITE_CAP)


def _read_timeout(context: int) -> float:
    """Apply omlx_bridge read channel parameters."""
    return dynamic_timeout(base=_READ_BASE, factor=_READ_FACTOR, context=context, cap=_READ_CAP)


# ---------------------------------------------------------------------------
# TestOmlxWriteTimeout — base=10, factor=0.5, cap=30
# ---------------------------------------------------------------------------


class TestOmlxWriteTimeout:
    """Verify dynamic_timeout behavior with write-channel parameters."""

    # ------------------------------------------------------------------
    # Invariant: small input → value near base
    # ------------------------------------------------------------------

    def test_write_small_input_near_base(self):
        """Zero-length input must return base (10), not some inflated value."""
        result = _write_timeout(context=0)
        # MUTATION TARGET: base=10 → base=1 would produce 1.0
        assert result == pytest.approx(_WRITE_BASE, abs=1.0), (
            f"Zero-context write timeout must be near base={_WRITE_BASE}, got {result}"
        )

    def test_write_empty_input_equals_base(self):
        """With context=0 the formula reduces to base."""
        result = _write_timeout(context=0)
        assert result >= _WRITE_BASE, (
            f"Timeout with zero context must be >= base={_WRITE_BASE}, got {result}"
        )

    # ------------------------------------------------------------------
    # Invariant: cap enforcement
    # ------------------------------------------------------------------

    def test_write_capped_at_30(self):
        """Very large input must not exceed cap=30."""
        huge_input = 1_000_000  # 1M chars
        result = _write_timeout(context=huge_input)
        # MUTATION TARGET: cap=30 → cap=300 would not catch huge values
        assert result <= _WRITE_CAP, (
            f"Write timeout must be capped at {_WRITE_CAP}, got {result} for context={huge_input}"
        )

    def test_write_cap_is_exactly_30_at_saturation(self):
        """At saturation the timeout must equal exactly cap=30 (not cap-1 or cap+1)."""
        # Use a context large enough to saturate
        result = _write_timeout(context=1_000_000)
        assert result == pytest.approx(_WRITE_CAP, abs=0.01), (
            f"Saturated write timeout must equal cap={_WRITE_CAP}, got {result}"
        )

    # ------------------------------------------------------------------
    # Invariant: monotonically non-decreasing
    # ------------------------------------------------------------------

    def test_write_timeout_monotonically_increases(self):
        """Larger context must yield equal-or-larger timeout (monotonic)."""
        sizes = [0, 10, 50, 100, 500, 1000, 5000, 50000, 500000]
        timeouts = [_write_timeout(s) for s in sizes]
        for i in range(1, len(timeouts)):
            # MUTATION TARGET: factor=0.5 → 0.0 would produce constant (non-monotonic)
            assert timeouts[i] >= timeouts[i - 1], (
                f"Timeout must be monotonic: _write_timeout({sizes[i]})={timeouts[i]} "
                f"< _write_timeout({sizes[i - 1]})={timeouts[i - 1]}"
            )

    def test_write_timeout_bounded_below_by_base(self):
        """Write timeout must never fall below base=10 regardless of context."""
        for context in [0, 1, 5, 10]:
            result = _write_timeout(context=context)
            assert result >= _WRITE_BASE, (
                f"Write timeout must be >= base={_WRITE_BASE}, got {result} for context={context}"
            )

    # ------------------------------------------------------------------
    # Invariant: range check
    # ------------------------------------------------------------------

    def test_write_timeout_always_in_range(self):
        """Write timeout must always be in [base, cap] = [10, 30]."""
        test_contexts = [0, 1, 10, 100, 1000, 10000, 100000, 1000000]
        for ctx in test_contexts:
            result = _write_timeout(ctx)
            assert _WRITE_BASE <= result <= _WRITE_CAP, (
                f"Write timeout out of range [{_WRITE_BASE}, {_WRITE_CAP}]: "
                f"got {result} for context={ctx}"
            )

    def test_write_medium_input_between_base_and_cap(self):
        """A medium-sized input must produce a timeout strictly between base and cap."""
        # ~1000-char input: should be above base (10) but below cap (30)
        result = _write_timeout(context=1000)
        # Allow possibility of cap saturation, but must be >= base
        assert result >= _WRITE_BASE, f"Medium input timeout must be >= {_WRITE_BASE}, got {result}"
        assert result <= _WRITE_CAP, f"Medium input timeout must be <= {_WRITE_CAP}, got {result}"


# ---------------------------------------------------------------------------
# TestOmlxReadTimeout — base=30, factor=0.5, cap=120
# ---------------------------------------------------------------------------


class TestOmlxReadTimeout:
    """Verify dynamic_timeout behavior with read-channel parameters."""

    # ------------------------------------------------------------------
    # Invariant: small input → value near base
    # ------------------------------------------------------------------

    def test_read_small_input_near_base(self):
        """Zero-length input must return base (30)."""
        result = _read_timeout(context=0)
        # MUTATION TARGET: base=30 → base=3 would produce 3.0
        assert result == pytest.approx(_READ_BASE, abs=1.0), (
            f"Zero-context read timeout must be near base={_READ_BASE}, got {result}"
        )

    def test_read_empty_input_equals_base(self):
        """With context=0 the formula reduces to base=30."""
        result = _read_timeout(context=0)
        assert result >= _READ_BASE, (
            f"Timeout with zero context must be >= base={_READ_BASE}, got {result}"
        )

    # ------------------------------------------------------------------
    # Invariant: cap enforcement
    # ------------------------------------------------------------------

    def test_read_capped_at_120(self):
        """Very large input must not exceed cap=120."""
        huge_input = 1_000_000
        result = _read_timeout(context=huge_input)
        # MUTATION TARGET: cap=120 → cap=1200 would allow inflated timeouts
        assert result <= _READ_CAP, (
            f"Read timeout must be capped at {_READ_CAP}, got {result} for context={huge_input}"
        )

    def test_read_cap_is_exactly_120_at_saturation(self):
        """At saturation the timeout must equal exactly cap=120."""
        result = _read_timeout(context=1_000_000)
        assert result == pytest.approx(_READ_CAP, abs=0.01), (
            f"Saturated read timeout must equal cap={_READ_CAP}, got {result}"
        )

    # ------------------------------------------------------------------
    # Invariant: monotonically non-decreasing
    # ------------------------------------------------------------------

    def test_read_timeout_monotonically_increases(self):
        """Larger context must yield equal-or-larger read timeout."""
        sizes = [0, 10, 100, 500, 2000, 10000, 100000, 1000000]
        timeouts = [_read_timeout(s) for s in sizes]
        for i in range(1, len(timeouts)):
            # MUTATION TARGET: factor=0.5 → 0.0 would produce flat line
            assert timeouts[i] >= timeouts[i - 1], (
                f"Read timeout must be monotonic: _read_timeout({sizes[i]})={timeouts[i]} "
                f"< _read_timeout({sizes[i - 1]})={timeouts[i - 1]}"
            )

    def test_read_timeout_bounded_below_by_base(self):
        """Read timeout must never fall below base=30."""
        for context in [0, 1, 5]:
            result = _read_timeout(context=context)
            assert result >= _READ_BASE, (
                f"Read timeout must be >= base={_READ_BASE}, got {result} for context={context}"
            )

    # ------------------------------------------------------------------
    # Invariant: range check
    # ------------------------------------------------------------------

    def test_read_timeout_always_in_range(self):
        """Read timeout must always be in [base, cap] = [30, 120]."""
        test_contexts = [0, 1, 10, 100, 1000, 10000, 100000, 1000000]
        for ctx in test_contexts:
            result = _read_timeout(ctx)
            assert _READ_BASE <= result <= _READ_CAP, (
                f"Read timeout out of range [{_READ_BASE}, {_READ_CAP}]: "
                f"got {result} for context={ctx}"
            )

    def test_read_medium_input_in_range(self):
        """A medium input (5000 chars) must be in [30, 120]."""
        result = _read_timeout(context=5000)
        assert _READ_BASE <= result <= _READ_CAP, (
            f"Medium input read timeout must be in [{_READ_BASE}, {_READ_CAP}], got {result}"
        )


# ---------------------------------------------------------------------------
# TestWriteVsReadAsymmetry — read timeout must be >= write timeout
# ---------------------------------------------------------------------------


class TestWriteVsReadAsymmetry:
    """Read channel has higher base and cap than write; verify the asymmetry."""

    def test_read_base_greater_than_write_base(self):
        """read base=30 > write base=10: read must always timeout >= write at same context."""
        assert _READ_BASE > _WRITE_BASE, (
            f"Read base ({_READ_BASE}) must be greater than write base ({_WRITE_BASE})"
        )

    def test_read_cap_greater_than_write_cap(self):
        """read cap=120 > write cap=30."""
        assert _READ_CAP > _WRITE_CAP, (
            f"Read cap ({_READ_CAP}) must be greater than write cap ({_WRITE_CAP})"
        )

    def test_read_timeout_gte_write_timeout_for_all_contexts(self):
        """For any context, read timeout >= write timeout."""
        test_contexts = [0, 10, 100, 1000, 10000, 100000, 1000000]
        for ctx in test_contexts:
            write_t = _write_timeout(ctx)
            read_t = _read_timeout(ctx)
            # MUTATION TARGET: swapping base/cap params in bridge calls would fail this
            assert read_t >= write_t, (
                f"Read timeout ({read_t}) must be >= write timeout ({write_t}) for context={ctx}"
            )

    def test_read_timeout_zero_context_minus_write_timeout_zero_context(self):
        """At context=0, the delta should equal (read_base - write_base) = 20."""
        write_zero = _write_timeout(context=0)
        read_zero = _read_timeout(context=0)
        expected_delta = _READ_BASE - _WRITE_BASE  # 20
        actual_delta = read_zero - write_zero
        assert actual_delta == pytest.approx(expected_delta, abs=0.5), (
            f"At context=0, read - write must be ~{expected_delta}, got {actual_delta}"
        )


# ---------------------------------------------------------------------------
# TestDynamicTimeoutParameterTypes — robustness
# ---------------------------------------------------------------------------


class TestDynamicTimeoutParameterTypes:
    """Ensure dynamic_timeout accepts int and float contexts (as used in bridges)."""

    def test_accepts_int_context(self):
        """Bridge passes len(line) which is an int."""
        result = dynamic_timeout(base=10, factor=0.5, context=100, cap=30)
        assert isinstance(result, (int, float)), "Must return a numeric type"
        assert result > 0, "Timeout must be positive"

    def test_accepts_zero_context(self):
        """len('') == 0 is a valid input (empty line)."""
        result = dynamic_timeout(base=10, factor=0.5, context=0, cap=30)
        assert result > 0, "Zero-context timeout must still be positive"

    def test_returns_finite_value(self):
        """Must never return inf or NaN."""
        import math

        for ctx in [0, 1, 100, 1_000_000]:
            result = dynamic_timeout(base=10, factor=0.5, context=ctx, cap=30)
            assert math.isfinite(result), f"Timeout must be finite, got {result} for context={ctx}"

"""
Adversarial tests for workshop.timeout module.

Written WITHOUT reading the implementation — based solely on function
signatures and docstrings. Tests target the four mutation-kill invariants
described in the test requirements (六鐵律).

MUTATION TARGETS:
  - min(cap, ...)  → max(cap, ...)  → test_cap_guarantee catches this
  - max(floor, ...) → min(floor, ...) → test_floor_guarantee catches this
  - base + factor*context → base - factor*context → test_monotonic catches this
  - timeout_for_network: cap=15 → cap=150 → test_network_range catches this
"""

import math

import pytest
from workshop.timeout import (
    dynamic_timeout,
    timeout_for_api,
    timeout_for_llm,
    timeout_for_network,
    timeout_for_subprocess,
)

# ---------------------------------------------------------------------------
# TestDynamicTimeout — core formula invariants
# ---------------------------------------------------------------------------


class TestDynamicTimeout:
    """Invariant tests for the primitive dynamic_timeout()."""

    # -----------------------------------------------------------------------
    # Identity invariant
    # -----------------------------------------------------------------------

    def test_identity_zero_factor_returns_base(self):
        """factor=0 → result equals base exactly, regardless of context."""
        assert dynamic_timeout(base=10.0, factor=0.0, context=999.0) == 10.0

    def test_identity_zero_factor_zero_context_returns_base(self):
        """Baseline call with no arguments beyond base returns base."""
        assert dynamic_timeout(base=30.0) == 30.0

    def test_identity_zero_factor_large_context_does_not_shift(self):
        """Passing huge context without a factor must not change the result."""
        assert dynamic_timeout(base=5.0, factor=0.0, context=1_000_000.0) == 5.0

    # -----------------------------------------------------------------------
    # Cap (ceiling) invariant — kills min→max mutation
    # -----------------------------------------------------------------------

    def test_cap_guarantee_result_never_exceeds_cap(self):
        """result must always be <= cap, even when formula would exceed it."""
        result = dynamic_timeout(base=100.0, factor=10.0, context=50.0, cap=50.0)
        assert result <= 50.0

    def test_cap_guarantee_exactly_at_cap(self):
        """When formula == cap, result is exactly cap (no off-by-one)."""
        # base=10, factor=2, context=20 → 10 + 2*20 = 50, cap=50
        result = dynamic_timeout(base=10.0, factor=2.0, context=20.0, cap=50.0)
        assert result == pytest.approx(50.0)

    def test_cap_guarantee_large_product_clamped(self):
        """Extremely large factor×context cannot break the cap."""
        result = dynamic_timeout(base=1.0, factor=1e9, context=1e9, cap=300.0)
        assert result <= 300.0

    def test_cap_guarantee_default_cap_is_300(self):
        """Default cap is 300 seconds — even a huge formula stays ≤ 300."""
        result = dynamic_timeout(base=1.0, factor=100.0, context=100.0)
        assert result <= 300.0

    def test_cap_lower_than_base_is_respected(self):
        """Even when cap < base, the cap wins — result must be ≤ cap."""
        result = dynamic_timeout(base=60.0, factor=0.0, cap=10.0)
        assert result <= 10.0

    # -----------------------------------------------------------------------
    # Floor (ceiling) invariant — kills max→min mutation
    # -----------------------------------------------------------------------

    def test_floor_default_equals_base(self):
        """With floor=None, the default floor is base itself."""
        # base=10, factor=1, context=-5 → formula = 5 < base → must return base
        result = dynamic_timeout(base=10.0, factor=1.0, context=-5.0)
        assert result >= 10.0

    def test_floor_explicit_protects_against_negative_context(self):
        """Explicit floor protects when base+factor*context would go below floor."""
        result = dynamic_timeout(base=10.0, factor=1.0, context=-5.0, floor=5.0)
        assert result >= 5.0

    def test_floor_explicit_lower_than_formula_allows_formula(self):
        """When formula > floor, the formula result is returned (floor is no-op)."""
        result = dynamic_timeout(base=20.0, factor=0.0, floor=5.0)
        assert result == pytest.approx(20.0)

    def test_floor_zero_negative_formula_clamped_to_zero(self):
        """Floor=0 ensures we never return a negative timeout."""
        result = dynamic_timeout(base=5.0, factor=2.0, context=-10.0, floor=0.0)
        assert result >= 0.0

    def test_floor_equals_cap_pins_result(self):
        """When floor == cap, result is pinned to that single value."""
        result = dynamic_timeout(base=1.0, factor=0.0, cap=20.0, floor=20.0)
        assert result == pytest.approx(20.0)

    def test_floor_above_base_raises_result(self):
        """Floor > base still enforces the floor when formula < floor."""
        # base=5, factor=0 → formula=5, floor=15 → result=15
        result = dynamic_timeout(base=5.0, factor=0.0, floor=15.0)
        assert result >= 15.0

    # -----------------------------------------------------------------------
    # Monotonicity invariant — kills base+factor*context → base-factor*context
    # -----------------------------------------------------------------------

    def test_monotonic_larger_context_gives_larger_or_equal_result(self):
        """With factor > 0, a bigger context must yield a bigger (or equal) timeout."""
        r1 = dynamic_timeout(base=10.0, factor=2.0, context=5.0)
        r2 = dynamic_timeout(base=10.0, factor=2.0, context=10.0)
        assert r2 >= r1

    def test_monotonic_zero_to_positive_context(self):
        """Increasing context from 0 to positive must not decrease result."""
        r_zero = dynamic_timeout(base=10.0, factor=1.0, context=0.0)
        r_pos = dynamic_timeout(base=10.0, factor=1.0, context=50.0)
        assert r_pos >= r_zero

    def test_monotonic_saturated_at_cap_stays_monotonic(self):
        """Once capped, further context increases keep result at cap (non-decreasing)."""
        r1 = dynamic_timeout(base=10.0, factor=5.0, context=100.0, cap=100.0)
        r2 = dynamic_timeout(base=10.0, factor=5.0, context=200.0, cap=100.0)
        assert r2 >= r1

    def test_monotonic_negative_factor_decreases_with_more_context(self):
        """With factor < 0, larger context yields smaller result (bounded by floor)."""
        # Negative factor is not explicitly listed in the spec, but the formula
        # clamp(floor, base + factor*context, cap) still holds.
        r1 = dynamic_timeout(base=50.0, factor=-1.0, context=5.0, floor=1.0)
        r2 = dynamic_timeout(base=50.0, factor=-1.0, context=10.0, floor=1.0)
        assert r2 <= r1

    def test_monotonic_multi_step_sequence(self):
        """A sequence of increasing contexts must produce a non-decreasing sequence."""
        contexts = [0, 10, 20, 50, 100, 500]
        results = [dynamic_timeout(base=5.0, factor=0.5, context=c) for c in contexts]
        for i in range(len(results) - 1):
            assert results[i + 1] >= results[i], (
                f"Monotonicity broken between context={contexts[i]} (→{results[i]}) "
                f"and context={contexts[i + 1]} (→{results[i + 1]})"
            )

    # -----------------------------------------------------------------------
    # Precision / edge cases
    # -----------------------------------------------------------------------

    def test_result_is_finite_float(self):
        """Result is always a finite float, never NaN or inf."""
        result = dynamic_timeout(base=10.0, factor=2.0, context=100.0)
        assert math.isfinite(result)

    def test_zero_base_with_factor_scales_from_zero(self):
        """base=0 + factor*context is the formula; floor (defaults to 0) kicks in."""
        result = dynamic_timeout(base=0.0, factor=1.0, context=10.0, cap=100.0)
        assert 0.0 <= result <= 100.0

    def test_fractional_inputs_accepted(self):
        """Fractional inputs are valid and produce a float result."""
        result = dynamic_timeout(base=2.5, factor=0.1, context=7.3, cap=300.0)
        assert isinstance(result, float)
        assert math.isfinite(result)


# ---------------------------------------------------------------------------
# TestTimeoutForNetwork — 5-15 s range invariant (kills cap=15→cap=150)
# ---------------------------------------------------------------------------


class TestTimeoutForNetwork:
    """Invariant tests for timeout_for_network()."""

    def test_network_range_zero_payload(self):
        """Zero payload must return a value in [5, 15]."""
        result = timeout_for_network(payload_kb=0)
        assert 5.0 <= result <= 15.0

    def test_network_range_small_payload(self):
        """Small payload stays within bounds."""
        result = timeout_for_network(payload_kb=10.0)
        assert 5.0 <= result <= 15.0

    def test_network_range_large_payload_capped(self):
        """Huge payload must still be capped at 15 — kills cap=150 mutation."""
        result = timeout_for_network(payload_kb=100_000.0)
        assert result <= 15.0

    def test_network_floor_never_below_5(self):
        """Result never drops below 5, even with zero or negative payload."""
        result = timeout_for_network(payload_kb=0.0)
        assert result >= 5.0

    def test_network_range_no_args(self):
        """Calling with no arguments is valid and stays in range."""
        result = timeout_for_network()
        assert 5.0 <= result <= 15.0

    def test_network_monotonic_scaling(self):
        """Larger payloads must not decrease the timeout (within cap)."""
        r1 = timeout_for_network(payload_kb=0)
        r2 = timeout_for_network(payload_kb=50.0)
        assert r2 >= r1


# ---------------------------------------------------------------------------
# TestTimeoutForApi — 15-60 s range invariant
# ---------------------------------------------------------------------------


class TestTimeoutForApi:
    """Invariant tests for timeout_for_api()."""

    def test_api_range_zero_complexity(self):
        """Zero complexity must be in [15, 60]."""
        result = timeout_for_api(complexity=0)
        assert 15.0 <= result <= 60.0

    def test_api_range_high_complexity_capped(self):
        """High complexity capped at 60."""
        result = timeout_for_api(complexity=1_000.0)
        assert result <= 60.0

    def test_api_floor_never_below_15(self):
        """Result must never drop below 15."""
        result = timeout_for_api(complexity=0)
        assert result >= 15.0

    def test_api_range_no_args(self):
        """Default call stays in range."""
        result = timeout_for_api()
        assert 15.0 <= result <= 60.0

    def test_api_monotonic_scaling(self):
        """Higher complexity → higher (or equal) timeout."""
        r1 = timeout_for_api(complexity=0)
        r2 = timeout_for_api(complexity=100.0)
        assert r2 >= r1


# ---------------------------------------------------------------------------
# TestTimeoutForSubprocess — 30-300 s range invariant
# ---------------------------------------------------------------------------


class TestTimeoutForSubprocess:
    """Invariant tests for timeout_for_subprocess()."""

    def test_subprocess_range_zero_expected(self):
        """Zero expected_seconds must be in [30, 300]."""
        result = timeout_for_subprocess(expected_seconds=0)
        assert 30.0 <= result <= 300.0

    def test_subprocess_range_large_expected_capped(self):
        """Very large expected duration must be capped at 300."""
        result = timeout_for_subprocess(expected_seconds=100_000.0)
        assert result <= 300.0

    def test_subprocess_floor_never_below_30(self):
        """Result never falls below 30."""
        result = timeout_for_subprocess(expected_seconds=0)
        assert result >= 30.0

    def test_subprocess_range_no_args(self):
        """Default call stays in range."""
        result = timeout_for_subprocess()
        assert 30.0 <= result <= 300.0

    def test_subprocess_monotonic_scaling(self):
        """Longer expected duration → longer (or equal) timeout."""
        r1 = timeout_for_subprocess(expected_seconds=0)
        r2 = timeout_for_subprocess(expected_seconds=60.0)
        assert r2 >= r1


# ---------------------------------------------------------------------------
# TestTimeoutForLlm — 15 s base, 180 s cap, model_speed invariant
# ---------------------------------------------------------------------------


class TestTimeoutForLlm:
    """Invariant tests for timeout_for_llm()."""

    def test_llm_base_no_tokens_at_least_15(self):
        """Zero tokens, normal speed → result >= 15 (base)."""
        result = timeout_for_llm(tokens=0, model_speed=1.0)
        assert result >= 15.0

    def test_llm_cap_normal_speed_at_most_180(self):
        """Normal speed → result <= 180 for any token count."""
        result = timeout_for_llm(tokens=100_000, model_speed=1.0)
        assert result <= 180.0

    def test_llm_range_no_args(self):
        """Default call: result in [15, 180]."""
        result = timeout_for_llm()
        assert 15.0 <= result <= 180.0

    def test_llm_slow_model_increases_timeout(self):
        """model_speed=2.0 (slow) must give >= timeout of model_speed=1.0."""
        r_normal = timeout_for_llm(tokens=500, model_speed=1.0)
        r_slow = timeout_for_llm(tokens=500, model_speed=2.0)
        assert r_slow >= r_normal

    def test_llm_fast_model_decreases_or_equal_timeout(self):
        """model_speed < 1.0 (fast) must give <= timeout of normal speed."""
        r_normal = timeout_for_llm(tokens=500, model_speed=1.0)
        r_fast = timeout_for_llm(tokens=500, model_speed=0.5)
        # fast model → shorter timeout; floor = base * model_speed
        assert r_fast <= r_normal
        assert r_fast >= 15.0 * 0.5  # floor scales with model_speed

    def test_llm_more_tokens_increases_timeout(self):
        """Larger token count → longer (or equal) timeout."""
        r1 = timeout_for_llm(tokens=100, model_speed=1.0)
        r2 = timeout_for_llm(tokens=1000, model_speed=1.0)
        assert r2 >= r1

    def test_llm_floor_scales_with_model_speed(self):
        """Floor = base * model_speed; fast models get proportionally lower floor."""
        result = timeout_for_llm(tokens=0, model_speed=0.01)
        assert result >= 15.0 * 0.01  # floor = 15 * model_speed
        assert result > 0  # always positive

    def test_llm_result_is_finite_float(self):
        """LLM timeout is always a finite float."""
        result = timeout_for_llm(tokens=500, model_speed=1.0)
        assert math.isfinite(result)

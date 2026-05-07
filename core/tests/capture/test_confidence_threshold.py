"""M5 — Integration tests for _confidence_threshold across all enrichment strategies.

Verifies that the depth + adapter_type interaction is correct for every
adapter profile defined in ADAPTER_ENRICHMENT_PROFILES.
"""

from __future__ import annotations

import pytest
from src.modules.capture.enrichment_config import (
    ADAPTER_ENRICHMENT_PROFILES,
    get_enrichment_profile,
)
from src.modules.capture.services import _confidence_threshold

# ---------------------------------------------------------------------------
# Baseline: single-depth for all registered adapter types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("adapter_type", list(ADAPTER_ENRICHMENT_PROFILES.keys()))
def test_depth1_matches_profile_base(adapter_type: str):
    """depth=1 → profile_base + 0.05 × 1, clamped to [0.3, 0.8]."""
    profile_base = get_enrichment_profile(adapter_type)["confidence_threshold"]
    expected = max(0.3, min(0.8, profile_base + 0.05 * 1))
    assert _confidence_threshold(enrichment_depth=1, adapter_type=adapter_type) == pytest.approx(
        expected, abs=1e-9
    )


# ---------------------------------------------------------------------------
# Depth scaling — finance_transaction (strict profile)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "depth,expected",
    [
        # base=0.65; depth × 0.05 increments, clamped at 0.8
        (0, pytest.approx(0.65)),
        (1, pytest.approx(0.70)),
        (2, pytest.approx(0.75)),
        (3, pytest.approx(0.80)),  # hits ceiling
        (5, pytest.approx(0.80)),  # stays at ceiling
    ],
)
def test_finance_transaction_depth_scaling(depth: int, expected):
    result = _confidence_threshold(enrichment_depth=depth, adapter_type="finance_transaction")
    assert result == expected


# ---------------------------------------------------------------------------
# Depth scaling — webcrawl (lenient profile)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "depth,expected",
    [
        # base=0.35; floor at 0.3 prevents going below
        (0, pytest.approx(0.35)),
        (1, pytest.approx(0.40)),
        (2, pytest.approx(0.45)),
        (9, pytest.approx(0.80)),  # 0.35 + 0.45 = 0.80, ceiling
    ],
)
def test_webcrawl_depth_scaling(depth: int, expected):
    result = _confidence_threshold(enrichment_depth=depth, adapter_type="webcrawl")
    assert result == expected


# ---------------------------------------------------------------------------
# Unknown / None adapter_type → generic fallback
# ---------------------------------------------------------------------------


def test_none_adapter_type_falls_back_to_generic():
    generic_base = get_enrichment_profile(None)["confidence_threshold"]
    expected = max(0.3, min(0.8, generic_base + 0.05))
    assert _confidence_threshold(enrichment_depth=1, adapter_type=None) == pytest.approx(expected)


def test_unknown_adapter_type_falls_back_to_generic():
    generic_base = get_enrichment_profile("nonexistent_adapter")["confidence_threshold"]
    expected = max(0.3, min(0.8, generic_base + 0.05))
    assert _confidence_threshold(
        enrichment_depth=1, adapter_type="nonexistent_adapter"
    ) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Clamp invariants — result is always in [0.3, 0.8]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("adapter_type", list(ADAPTER_ENRICHMENT_PROFILES.keys()))
@pytest.mark.parametrize("depth", [0, 1, 3, 10, 100])
def test_result_always_within_clamp_bounds(adapter_type: str, depth: int):
    result = _confidence_threshold(enrichment_depth=depth, adapter_type=adapter_type)
    assert 0.3 <= result <= 0.8, (
        f"Out-of-range result {result} for adapter={adapter_type!r} depth={depth}"
    )


# ---------------------------------------------------------------------------
# Strict > lenient: finance profiles should always be ≥ webcrawl at same depth
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("depth", [0, 1, 2, 3])
def test_strict_adapter_gte_lenient(depth: int):
    finance = _confidence_threshold(enrichment_depth=depth, adapter_type="finance_transaction")
    webcrawl = _confidence_threshold(enrichment_depth=depth, adapter_type="webcrawl")
    assert finance >= webcrawl, (
        f"finance ({finance}) should be >= webcrawl ({webcrawl}) at depth={depth}"
    )

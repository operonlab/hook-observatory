"""M5 (issue #28): regression test for capture._confidence_threshold.

Covers the multi-strategy combinations of adapter profile x enrichment depth
that were previously not exercised. The threshold is clamped to [0.3, 0.8]
and increases by 0.05 per enrichment depth level on top of the per-adapter
profile base.
"""

from __future__ import annotations

import pytest
from src.modules.capture.services import _confidence_threshold


class TestConfidenceThresholdClamp:
    """Threshold must stay inside [0.3, 0.8] regardless of inputs."""

    @pytest.mark.parametrize("depth", [-100, -1, 0, 1, 5, 100])
    def test_clamped_to_range(self, depth: int) -> None:
        for adapter_type in (None, "generic", "finance_transaction", "webcrawl"):
            threshold = _confidence_threshold(
                enrichment_depth=depth, adapter_type=adapter_type
            )
            assert 0.3 <= threshold <= 0.8


class TestConfidenceThresholdProfileSelection:
    """Different adapter_types yield different profile bases."""

    def test_unknown_adapter_falls_back_to_generic(self) -> None:
        unknown = _confidence_threshold(adapter_type="not_a_real_adapter")
        generic = _confidence_threshold(adapter_type="generic")
        assert unknown == generic

    def test_none_adapter_falls_back_to_generic(self) -> None:
        none_threshold = _confidence_threshold(adapter_type=None)
        generic = _confidence_threshold(adapter_type="generic")
        assert none_threshold == generic


class TestConfidenceThresholdDepthMonotonic:
    """Deeper enrichment should not lower the bar (monotonic non-decreasing)."""

    @pytest.mark.parametrize(
        "adapter_type",
        ["generic", "finance_transaction", "webcrawl"],
    )
    def test_depth_increases_threshold(self, adapter_type: str) -> None:
        prev = _confidence_threshold(enrichment_depth=0, adapter_type=adapter_type)
        for depth in range(1, 6):
            current = _confidence_threshold(
                enrichment_depth=depth, adapter_type=adapter_type
            )
            # Either it grew, or it hit the upper clamp at 0.8.
            assert current >= prev or current == 0.8
            prev = current


class TestConfidenceThresholdAsymmetric:
    """Asymmetric profile contract: stricter adapters should expose a higher
    base than `generic` at depth=0 (pre-clamp). If the profile system later
    diverges from this assumption the test will surface it."""

    def test_finance_transaction_at_least_as_strict_as_generic(self) -> None:
        finance = _confidence_threshold(
            enrichment_depth=0, adapter_type="finance_transaction"
        )
        generic = _confidence_threshold(enrichment_depth=0, adapter_type="generic")
        assert finance >= generic

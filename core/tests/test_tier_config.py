"""Unit tests for core.src.shared.tier_config module."""

import dataclasses

import pytest
from core.src.shared.tier_config import (
    BLOB_THRESHOLD_BYTES,
    LIFECYCLE_BATCH_SIZE,
    S3_ARCHIVE_BUCKET,
    S3_FROZEN_BUCKET,
    TIER_THRESHOLDS,
    TierThreshold,
    get_frozen_retention_cutoff,
    get_retention_summary,
    get_threshold,
    get_tier,
)


# ---------------------------------------------------------------------------
# 1. TierThreshold dataclass -- frozen, immutable
# ---------------------------------------------------------------------------
class TestTierThreshold:
    def test_fields_accessible(self):
        t = TierThreshold(hot_days=14, warm_days=180, cold_days=1095)
        assert t.hot_days == 14
        assert t.warm_days == 180
        assert t.cold_days == 1095
        assert t.frozen_retention_years == 5  # default

    def test_custom_frozen_retention(self):
        t = TierThreshold(hot_days=30, warm_days=90, cold_days=365, frozen_retention_years=10)
        assert t.frozen_retention_years == 10

    def test_frozen_immutable(self):
        t = TierThreshold(hot_days=14, warm_days=180, cold_days=1095)
        with pytest.raises(dataclasses.FrozenInstanceError):
            t.hot_days = 999  # type: ignore[misc]

    def test_frozen_immutable_all_fields(self):
        t = TierThreshold(hot_days=14, warm_days=180, cold_days=1095)
        with pytest.raises(dataclasses.FrozenInstanceError):
            t.warm_days = 0  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            t.cold_days = 0  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            t.frozen_retention_years = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. TIER_THRESHOLDS -- all 5 modules present
# ---------------------------------------------------------------------------
class TestTierThresholdsRegistry:
    EXPECTED_MODULES = {"memvault", "intelflow", "finance", "taskflow", "ideagraph"}

    def test_all_modules_present(self):
        assert set(TIER_THRESHOLDS.keys()) == self.EXPECTED_MODULES

    def test_all_values_are_tier_threshold(self):
        for module, threshold in TIER_THRESHOLDS.items():
            assert isinstance(threshold, TierThreshold), f"{module} value is not TierThreshold"

    def test_thresholds_monotonically_increasing(self):
        """hot_days < warm_days < cold_days for every module."""
        for module, t in TIER_THRESHOLDS.items():
            assert t.hot_days < t.warm_days < t.cold_days, (
                f"{module}: thresholds not monotonically increasing "
                f"({t.hot_days}, {t.warm_days}, {t.cold_days})"
            )


# ---------------------------------------------------------------------------
# 3. get_tier() -- boundary tests for each module
# ---------------------------------------------------------------------------
class TestGetTier:
    """Test tier classification at exact boundaries for every known module."""

    @pytest.mark.parametrize("module", list(TIER_THRESHOLDS.keys()))
    def test_age_zero_is_hot(self, module: str):
        assert get_tier(module, 0) == "hot"

    @pytest.mark.parametrize("module", list(TIER_THRESHOLDS.keys()))
    def test_at_hot_boundary_is_hot(self, module: str):
        t = TIER_THRESHOLDS[module]
        assert get_tier(module, t.hot_days) == "hot"

    @pytest.mark.parametrize("module", list(TIER_THRESHOLDS.keys()))
    def test_hot_plus_one_is_warm(self, module: str):
        t = TIER_THRESHOLDS[module]
        assert get_tier(module, t.hot_days + 1) == "warm"

    @pytest.mark.parametrize("module", list(TIER_THRESHOLDS.keys()))
    def test_at_warm_boundary_is_warm(self, module: str):
        t = TIER_THRESHOLDS[module]
        assert get_tier(module, t.warm_days) == "warm"

    @pytest.mark.parametrize("module", list(TIER_THRESHOLDS.keys()))
    def test_warm_plus_one_is_cold(self, module: str):
        t = TIER_THRESHOLDS[module]
        assert get_tier(module, t.warm_days + 1) == "cold"

    @pytest.mark.parametrize("module", list(TIER_THRESHOLDS.keys()))
    def test_at_cold_boundary_is_cold(self, module: str):
        t = TIER_THRESHOLDS[module]
        assert get_tier(module, t.cold_days) == "cold"

    @pytest.mark.parametrize("module", list(TIER_THRESHOLDS.keys()))
    def test_cold_plus_one_is_frozen(self, module: str):
        t = TIER_THRESHOLDS[module]
        assert get_tier(module, t.cold_days + 1) == "frozen"


# ---------------------------------------------------------------------------
# 4. get_tier() -- unknown module fallback
# ---------------------------------------------------------------------------
class TestGetTierUnknownModule:
    """Unknown modules should use default thresholds (90 / 365 / 1825)."""

    def test_unknown_age_zero_hot(self):
        assert get_tier("nonexistent_module", 0) == "hot"

    def test_unknown_at_hot_boundary(self):
        assert get_tier("nonexistent_module", 90) == "hot"

    def test_unknown_hot_plus_one_warm(self):
        assert get_tier("nonexistent_module", 91) == "warm"

    def test_unknown_at_warm_boundary(self):
        assert get_tier("nonexistent_module", 365) == "warm"

    def test_unknown_warm_plus_one_cold(self):
        assert get_tier("nonexistent_module", 366) == "cold"

    def test_unknown_at_cold_boundary(self):
        assert get_tier("nonexistent_module", 1825) == "cold"

    def test_unknown_cold_plus_one_frozen(self):
        assert get_tier("nonexistent_module", 1826) == "frozen"

    def test_unknown_very_large_age(self):
        assert get_tier("nonexistent_module", 999999) == "frozen"


# ---------------------------------------------------------------------------
# 5. get_threshold() -- known and unknown module
# ---------------------------------------------------------------------------
class TestGetThreshold:
    def test_known_module_returns_configured(self):
        t = get_threshold("memvault")
        assert t is TIER_THRESHOLDS["memvault"]

    def test_all_known_modules(self):
        for module in TIER_THRESHOLDS:
            assert get_threshold(module) is TIER_THRESHOLDS[module]

    def test_unknown_module_returns_default(self):
        t = get_threshold("unknown_module")
        assert t.hot_days == 90
        assert t.warm_days == 365
        assert t.cold_days == 1825
        assert t.frozen_retention_years == 5

    def test_unknown_module_returns_new_instance(self):
        """Each call for unknown module creates a fresh TierThreshold."""
        t1 = get_threshold("unknown_a")
        t2 = get_threshold("unknown_b")
        assert t1 == t2  # equal values
        assert t1 is not t2  # but distinct objects


# ---------------------------------------------------------------------------
# 6. get_frozen_retention_cutoff()
# ---------------------------------------------------------------------------
class TestGetFrozenRetentionCutoff:
    def test_memvault_cutoff(self):
        t = TIER_THRESHOLDS["memvault"]
        expected = t.cold_days + t.frozen_retention_years * 365
        assert get_frozen_retention_cutoff("memvault") == expected

    def test_all_modules_cutoff(self):
        for module, t in TIER_THRESHOLDS.items():
            expected = t.cold_days + t.frozen_retention_years * 365
            assert get_frozen_retention_cutoff(module) == expected, f"Failed for {module}"

    def test_unknown_module_cutoff(self):
        # default: cold_days=1825, frozen_retention_years=5
        expected = 1825 + 5 * 365
        assert get_frozen_retention_cutoff("unknown") == expected

    def test_finance_specific_value(self):
        """Finance: cold_days=1825, frozen=5y => 1825 + 1825 = 3650."""
        assert get_frozen_retention_cutoff("finance") == 1825 + 5 * 365


# ---------------------------------------------------------------------------
# 7. get_retention_summary()
# ---------------------------------------------------------------------------
class TestGetRetentionSummary:
    def test_all_modules_present(self):
        summary = get_retention_summary()
        assert set(summary.keys()) == set(TIER_THRESHOLDS.keys())

    def test_keys_per_module(self):
        expected_keys = {
            "hot_days",
            "warm_days",
            "cold_days",
            "frozen_retention_years",
            "total_retention_days",
            "total_retention_years",
        }
        summary = get_retention_summary()
        for module, info in summary.items():
            assert set(info.keys()) == expected_keys, f"Wrong keys for {module}"

    def test_values_match_thresholds(self):
        summary = get_retention_summary()
        for module, t in TIER_THRESHOLDS.items():
            info = summary[module]
            assert info["hot_days"] == t.hot_days
            assert info["warm_days"] == t.warm_days
            assert info["cold_days"] == t.cold_days
            assert info["frozen_retention_years"] == t.frozen_retention_years

    def test_total_retention_calculation(self):
        summary = get_retention_summary()
        for module, t in TIER_THRESHOLDS.items():
            info = summary[module]
            expected_days = t.cold_days + t.frozen_retention_years * 365
            assert info["total_retention_days"] == expected_days, f"Wrong total days for {module}"
            assert info["total_retention_years"] == round(expected_days / 365, 1), (
                f"Wrong total years for {module}"
            )

    def test_memvault_specific_retention(self):
        summary = get_retention_summary()
        mv = summary["memvault"]
        assert mv["hot_days"] == 14
        assert mv["warm_days"] == 180
        assert mv["cold_days"] == 1095
        assert mv["frozen_retention_years"] == 5
        assert mv["total_retention_days"] == 1095 + 5 * 365  # 2920
        assert mv["total_retention_years"] == round(2920 / 365, 1)  # 8.0


# ---------------------------------------------------------------------------
# 8. Constants
# ---------------------------------------------------------------------------
class TestConstants:
    def test_s3_archive_bucket(self):
        assert S3_ARCHIVE_BUCKET == "workshop-archive"

    def test_s3_frozen_bucket(self):
        assert S3_FROZEN_BUCKET == "workshop-frozen"

    def test_blob_threshold_bytes(self):
        assert BLOB_THRESHOLD_BYTES == 10240  # 10 KB

    def test_lifecycle_batch_size(self):
        assert LIFECYCLE_BATCH_SIZE == 500

    def test_constants_are_expected_types(self):
        assert isinstance(S3_ARCHIVE_BUCKET, str)
        assert isinstance(S3_FROZEN_BUCKET, str)
        assert isinstance(BLOB_THRESHOLD_BYTES, int)
        assert isinstance(LIFECYCLE_BATCH_SIZE, int)

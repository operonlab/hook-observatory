"""Import and syntax verification tests for four-tier lifecycle changes.

Validates that memvault and intelflow modules expose the expected symbols
for the Hot / Warm / Cold / Frozen data lifecycle architecture.

No DB connection needed -- pure import and introspection tests.
"""

import inspect

# ============================================================
# 1. src.shared.tier_config
# ============================================================


class TestTierConfigImports:
    """Verify tier_config module exports."""

    def test_import_tier_threshold(self):
        from src.shared.tier_config import TierThreshold

        assert TierThreshold is not None

    def test_import_get_tier(self):
        from src.shared.tier_config import get_tier

        assert callable(get_tier)

    def test_import_get_threshold(self):
        from src.shared.tier_config import get_threshold

        assert callable(get_threshold)

    def test_import_tier_thresholds_dict(self):
        from src.shared.tier_config import TIER_THRESHOLDS

        assert isinstance(TIER_THRESHOLDS, dict)
        assert "memvault" in TIER_THRESHOLDS
        assert "intelflow" in TIER_THRESHOLDS

    def test_get_tier_returns_valid_tier(self):
        from src.shared.tier_config import get_tier

        # memvault thresholds: hot=14, warm=180, cold=1095
        assert get_tier("memvault", 1) == "hot"
        assert get_tier("memvault", 14) == "hot"  # boundary: <= hot_days
        assert get_tier("memvault", 15) == "warm"  # just past hot
        assert get_tier("memvault", 180) == "warm"  # boundary: <= warm_days
        assert get_tier("memvault", 181) == "cold"  # just past warm
        assert get_tier("memvault", 1095) == "cold"  # boundary: <= cold_days
        assert get_tier("memvault", 1096) == "frozen"  # just past cold

    def test_get_threshold_returns_tier_threshold(self):
        from src.shared.tier_config import TierThreshold, get_threshold

        t = get_threshold("memvault")
        assert isinstance(t, TierThreshold)
        assert t.hot_days > 0
        assert t.warm_days > t.hot_days
        assert t.cold_days > t.warm_days


# ============================================================
# 2. src.shared.storage
# ============================================================


class TestStorageImports:
    """Verify storage module exports for frozen tier."""

    def test_import_compute_content_hash(self):
        from src.shared.storage import compute_content_hash

        assert callable(compute_content_hash)

    def test_import_upload_blob_compressed(self):
        from src.shared.storage import upload_blob_compressed

        assert callable(upload_blob_compressed)
        assert inspect.iscoroutinefunction(upload_blob_compressed)

    def test_import_download_and_decompress(self):
        from src.shared.storage import download_and_decompress

        assert callable(download_and_decompress)
        assert inspect.iscoroutinefunction(download_and_decompress)

    def test_import_verify_frozen_integrity(self):
        from src.shared.storage import verify_frozen_integrity

        assert callable(verify_frozen_integrity)
        assert inspect.iscoroutinefunction(verify_frozen_integrity)

    def test_import_is_s3_ref(self):
        from src.shared.storage import is_s3_ref

        assert callable(is_s3_ref)
        # Quick functional check
        assert is_s3_ref("s3://bucket/key") is True
        assert is_s3_ref("not-s3") is False
        assert is_s3_ref(None) is False

    def test_import_parse_s3_ref(self):
        from src.shared.storage import parse_s3_ref

        assert callable(parse_s3_ref)
        bucket, key = parse_s3_ref("s3://workshop-frozen/memvault/blk-123.json.zst")
        assert bucket == "workshop-frozen"
        assert key == "memvault/blk-123.json.zst"

    def test_compute_content_hash_deterministic(self):
        from src.shared.storage import compute_content_hash

        h1 = compute_content_hash("hello world")
        h2 = compute_content_hash("hello world")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest


# ============================================================
# 3. src.modules.memvault.models -- BlockFrozen
# ============================================================


class TestMemvaultBlockFrozen:
    """Verify BlockFrozen class exists and has expected columns."""

    def test_import_block_frozen(self):
        from src.modules.memvault.models import BlockFrozen

        assert BlockFrozen is not None

    def test_tablename(self):
        from src.modules.memvault.models import BlockFrozen

        assert BlockFrozen.__tablename__ == "blocks_frozen"

    def test_has_id_column(self):
        from src.modules.memvault.models import BlockFrozen

        assert hasattr(BlockFrozen, "id")

    def test_has_s3_uri_column(self):
        from src.modules.memvault.models import BlockFrozen

        assert hasattr(BlockFrozen, "s3_uri")

    def test_has_content_hash_column(self):
        from src.modules.memvault.models import BlockFrozen

        assert hasattr(BlockFrozen, "content_hash")

    def test_has_frozen_at_column(self):
        from src.modules.memvault.models import BlockFrozen

        assert hasattr(BlockFrozen, "frozen_at")

    def test_has_tags_column(self):
        from src.modules.memvault.models import BlockFrozen

        assert hasattr(BlockFrozen, "tags")

    def test_has_summary_column(self):
        from src.modules.memvault.models import BlockFrozen

        assert hasattr(BlockFrozen, "summary")

    def test_schema_is_memvault(self):
        from src.modules.memvault.models import BlockFrozen

        schema = BlockFrozen.__table_args__[-1].get("schema")
        assert schema == "memvault"


# ============================================================
# 4. src.modules.intelflow.models -- ReportFrozen
#    src.modules.briefing.models -- BriefingFrozen
# ============================================================


class TestIntelflowFrozenModels:
    """Verify ReportFrozen exists in intelflow."""

    def test_import_report_frozen(self):
        from src.modules.intelflow.models import ReportFrozen

        assert ReportFrozen is not None

    def test_report_frozen_tablename(self):
        from src.modules.intelflow.models import ReportFrozen

        assert ReportFrozen.__tablename__ == "reports_frozen"

    def test_report_frozen_schema(self):
        from src.modules.intelflow.models import ReportFrozen

        schema = ReportFrozen.__table_args__[-1].get("schema")
        assert schema == "intelflow"

    def test_report_frozen_has_s3_uri(self):
        from src.modules.intelflow.models import ReportFrozen

        assert hasattr(ReportFrozen, "s3_uri")
        assert hasattr(ReportFrozen, "content_hash")
        assert hasattr(ReportFrozen, "frozen_at")


class TestBriefingFrozenModels:
    """Verify BriefingFrozen exists in briefing module."""

    def test_import_briefing_frozen(self):
        from src.modules.briefing.models import BriefingFrozen

        assert BriefingFrozen is not None

    def test_briefing_frozen_tablename(self):
        from src.modules.briefing.models import BriefingFrozen

        assert BriefingFrozen.__tablename__ == "briefings_frozen"

    def test_briefing_frozen_schema(self):
        from src.modules.briefing.models import BriefingFrozen

        schema = BriefingFrozen.__table_args__[-1].get("schema")
        assert schema == "briefing"

    def test_briefing_frozen_has_s3_uri(self):
        from src.modules.briefing.models import BriefingFrozen

        assert hasattr(BriefingFrozen, "s3_uri")
        assert hasattr(BriefingFrozen, "content_hash")
        assert hasattr(BriefingFrozen, "frozen_at")


# ============================================================
# 5. src.modules.intelflow.search -- include_warm parameter
# ============================================================


class TestIntelflowSearchSignature:
    """Verify semantic_search function signature includes include_warm."""

    def test_import_semantic_search(self):
        from src.modules.intelflow.search import semantic_search

        assert callable(semantic_search)
        assert inspect.iscoroutinefunction(semantic_search)

    def test_include_warm_parameter(self):
        from src.modules.intelflow.search import semantic_search

        sig = inspect.signature(semantic_search)
        assert "include_warm" in sig.parameters, (
            f"include_warm not found in semantic_search params: {list(sig.parameters.keys())}"
        )

    def test_include_warm_default_is_true(self):
        from src.modules.intelflow.search import semantic_search

        sig = inspect.signature(semantic_search)
        param = sig.parameters["include_warm"]
        assert param.default is True, f"Expected include_warm default=True, got {param.default}"

    def test_include_archived_parameter(self):
        from src.modules.intelflow.search import semantic_search

        sig = inspect.signature(semantic_search)
        assert "include_archived" in sig.parameters

    def test_full_parameter_set(self):
        from src.modules.intelflow.search import semantic_search

        sig = inspect.signature(semantic_search)
        param_names = list(sig.parameters.keys())
        expected = {
            "db",
            "space_id",
            "query",
            "limit",
            "threshold",
            "include_archived",
            "include_warm",
        }
        assert expected.issubset(set(param_names)), f"Missing params: {expected - set(param_names)}"

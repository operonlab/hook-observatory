"""Unit tests for frozen tier functions in core/src/shared/storage.py.

Tests pure/synchronous helpers that need NO S3 connection:
- compute_content_hash (str + bytes)
- _zstd_compress / _zstd_decompress round-trip
- is_s3_ref
- parse_s3_ref
- S3_REF_PREFIX constant
"""

import hashlib
import sys
from pathlib import Path
from unittest import mock

import pytest

# Ensure core/ is importable (matches conftest.py convention)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.shared.storage import (
    S3_REF_PREFIX,
    _zstd_compress,
    _zstd_decompress,
    compute_content_hash,
    is_s3_ref,
    parse_s3_ref,
)

# ---------------------------------------------------------------------------
# S3_REF_PREFIX constant
# ---------------------------------------------------------------------------


class TestS3RefPrefix:
    def test_value(self):
        assert S3_REF_PREFIX == "s3://"

    def test_type(self):
        assert isinstance(S3_REF_PREFIX, str)


# ---------------------------------------------------------------------------
# compute_content_hash
# ---------------------------------------------------------------------------


class TestComputeContentHash:
    def test_str_input(self):
        text = "test content"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert compute_content_hash(text) == expected

    def test_bytes_input(self):
        raw = b"test content"
        expected = hashlib.sha256(raw).hexdigest()
        assert compute_content_hash(raw) == expected

    def test_str_and_bytes_same_content_match(self):
        """str and bytes representing identical content must produce the same hash."""
        text = "hello world"
        assert compute_content_hash(text) == compute_content_hash(text.encode("utf-8"))

    def test_empty_string(self):
        expected = hashlib.sha256(b"").hexdigest()
        assert compute_content_hash("") == expected

    def test_empty_bytes(self):
        expected = hashlib.sha256(b"").hexdigest()
        assert compute_content_hash(b"") == expected

    def test_unicode_content(self):
        text = "Unicode test"
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert compute_content_hash(text) == expected

    def test_hash_length(self):
        """SHA-256 hex digest is always 64 characters."""
        assert len(compute_content_hash("anything")) == 64

    def test_hash_is_hex(self):
        result = compute_content_hash("data")
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        """Same input always gives same hash."""
        data = "determinism check"
        assert compute_content_hash(data) == compute_content_hash(data)

    def test_different_inputs_differ(self):
        assert compute_content_hash("alpha") != compute_content_hash("beta")


# ---------------------------------------------------------------------------
# is_s3_ref
# ---------------------------------------------------------------------------


class TestIsS3Ref:
    def test_valid_ref(self):
        assert is_s3_ref("s3://bucket/key") is True

    def test_valid_ref_nested_key(self):
        assert is_s3_ref("s3://my-bucket/path/to/object.json.zst") is True

    def test_none(self):
        assert is_s3_ref(None) is False

    def test_empty_string(self):
        assert is_s3_ref("") is False

    def test_plain_text(self):
        assert is_s3_ref("plain text") is False

    def test_partial_prefix(self):
        assert is_s3_ref("s3:/bucket/key") is False

    def test_http_url(self):
        assert is_s3_ref("https://s3.amazonaws.com/bucket/key") is False

    def test_prefix_only(self):
        """Just the prefix with no bucket/key is still technically a valid startswith match."""
        assert is_s3_ref("s3://") is True

    def test_case_sensitive(self):
        assert is_s3_ref("S3://bucket/key") is False


# ---------------------------------------------------------------------------
# parse_s3_ref
# ---------------------------------------------------------------------------


class TestParseS3Ref:
    def test_basic(self):
        bucket, key = parse_s3_ref("s3://workshop-archive/intelflow/rpt-abc123")
        assert bucket == "workshop-archive"
        assert key == "intelflow/rpt-abc123"

    def test_simple_key(self):
        bucket, key = parse_s3_ref("s3://mybucket/mykey")
        assert bucket == "mybucket"
        assert key == "mykey"

    def test_nested_key(self):
        bucket, key = parse_s3_ref("s3://archive/a/b/c/file.json.zst")
        assert bucket == "archive"
        assert key == "a/b/c/file.json.zst"

    def test_no_key(self):
        """Bucket-only URI (no trailing slash)."""
        bucket, key = parse_s3_ref("s3://bucket-only")
        assert bucket == "bucket-only"
        assert key == ""

    def test_empty_key_with_slash(self):
        """Bucket with trailing slash gives empty key."""
        bucket, key = parse_s3_ref("s3://bucket/")
        assert bucket == "bucket"
        assert key == ""

    def test_roundtrip_with_is_s3_ref(self):
        """A URI that passes is_s3_ref should be parseable."""
        uri = "s3://frozen-tier/memvault/block-123.json.zst"
        assert is_s3_ref(uri)
        bucket, key = parse_s3_ref(uri)
        assert bucket == "frozen-tier"
        assert key == "memvault/block-123.json.zst"


# ---------------------------------------------------------------------------
# _zstd_compress / _zstd_decompress
# ---------------------------------------------------------------------------


# Detect whether zstandard is available at module level
_HAS_ZSTD = False
try:
    import zstandard  # noqa: F401

    _HAS_ZSTD = True
except ImportError:
    pass


class TestZstdWithLibrary:
    """Tests when zstandard IS available (real compression)."""

    @pytest.mark.skipif(not _HAS_ZSTD, reason="zstandard not installed")
    def test_roundtrip(self):
        original = b"The quick brown fox jumps over the lazy dog. " * 100
        compressed = _zstd_compress(original)
        decompressed = _zstd_decompress(compressed)
        assert decompressed == original

    @pytest.mark.skipif(not _HAS_ZSTD, reason="zstandard not installed")
    def test_compression_shrinks_data(self):
        original = b"aaaa" * 1000
        compressed = _zstd_compress(original)
        assert len(compressed) < len(original)


class TestZstdFallback:
    """Tests the graceful degradation path when zstandard is NOT installed."""

    @pytest.mark.skipif(_HAS_ZSTD, reason="zstandard IS installed, skip fallback test")
    def test_compress_fallback_returns_raw(self):
        """Without zstandard, _zstd_compress returns input unchanged."""
        data = b"uncompressed payload"
        result = _zstd_compress(data)
        assert result == data

    @pytest.mark.skipif(_HAS_ZSTD, reason="zstandard IS installed, skip fallback test")
    def test_decompress_fallback_returns_raw(self):
        """Without zstandard, _zstd_decompress returns input unchanged."""
        data = b"raw bytes"
        result = _zstd_decompress(data)
        assert result == data

    @pytest.mark.skipif(_HAS_ZSTD, reason="zstandard IS installed, skip fallback test")
    def test_roundtrip_fallback(self):
        """Fallback round-trip: compress then decompress gives original."""
        original = b"round-trip with fallback"
        compressed = _zstd_compress(original)
        decompressed = _zstd_decompress(compressed)
        assert decompressed == original


class TestZstdForcedFallback:
    """Force the ImportError path via mock, regardless of installed packages."""

    def test_compress_forced_fallback(self):
        data = b"mock fallback data"
        with mock.patch.dict(sys.modules, {"zstandard": None}):
            # Re-import to trigger the ImportError inside the function
            result = _zstd_compress(data)
            assert result == data

    def test_decompress_forced_fallback(self):
        data = b"mock fallback data"
        with mock.patch.dict(sys.modules, {"zstandard": None}):
            result = _zstd_decompress(data)
            assert result == data

    def test_roundtrip_forced_fallback(self):
        original = b"forced fallback round-trip"
        with mock.patch.dict(sys.modules, {"zstandard": None}):
            compressed = _zstd_compress(original)
            decompressed = _zstd_decompress(compressed)
            assert decompressed == original


# ---------------------------------------------------------------------------
# Integration: hash + compress round-trip
# ---------------------------------------------------------------------------


class TestFrozenTierIntegration:
    """Verify that hash computed before compress matches after decompress."""

    def test_hash_integrity_through_compression(self):
        content = "This is archived content for the frozen tier."
        content_bytes = content.encode("utf-8")

        hash_before = compute_content_hash(content_bytes)
        compressed = _zstd_compress(content_bytes)
        decompressed = _zstd_decompress(compressed)
        hash_after = compute_content_hash(decompressed)

        assert hash_before == hash_after

    def test_hash_str_through_compression(self):
        """Hash from str input, compress bytes, decompress, re-hash bytes must match."""
        text = "Unicode frozen content"
        hash_from_str = compute_content_hash(text)

        raw = text.encode("utf-8")
        decompressed = _zstd_decompress(_zstd_compress(raw))
        hash_from_bytes = compute_content_hash(decompressed)

        assert hash_from_str == hash_from_bytes

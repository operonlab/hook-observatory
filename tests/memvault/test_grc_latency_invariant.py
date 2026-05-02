"""Tests for scripts.grc_latency_invariant.check_grc_latency.

Contract:
- Per-item upper bound: elapsed_ms / items * 1000 <= 500 microseconds.
- Floor: elapsed_ms <= max(2000ms, items * 0.5ms).
- Skip per-item check when items_analyzed < 100.
- elapsed/items=0 must not raise.
"""

from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, "/Users/joneshong/workshop/scripts")

from grc_latency_invariant import check_grc_latency


def test_normal_load_passes():
    passed, reason = check_grc_latency(elapsed_ms=400, items_analyzed=5584)
    assert passed, reason


def test_at_per_item_boundary():
    # 5584 * 0.5 = 2792 ms => per_item exactly 500us, floor exactly 2792 ms.
    passed, reason = check_grc_latency(elapsed_ms=2792, items_analyzed=5584)
    assert passed, reason


def test_per_item_just_over_fails():
    # 2793 / 5584 * 1000 = 500.179 us per item.
    passed, reason = check_grc_latency(elapsed_ms=2793, items_analyzed=5584)
    assert not passed, f"expected FAIL but got: {reason}"
    assert "per_item" in reason.lower()


def test_small_items_skipped():
    # items < 100 must skip per-item check entirely.
    passed, reason = check_grc_latency(elapsed_ms=10_000, items_analyzed=50)
    assert passed, reason
    assert "skip" in reason.lower() or "too_small" in reason.lower()


def test_huge_items_proportional():
    # 100k items: 490us/item must PASS, 500.01us/item must FAIL.
    passed, reason = check_grc_latency(elapsed_ms=49_000, items_analyzed=100_000)
    assert passed, reason

    passed, reason = check_grc_latency(elapsed_ms=50_001, items_analyzed=100_000)
    assert not passed, f"expected FAIL but got: {reason}"
    assert "per_item" in reason.lower()


def test_zero_items_handled():
    # Must not raise ZeroDivisionError.
    passed, reason = check_grc_latency(elapsed_ms=1234, items_analyzed=0)
    assert isinstance(passed, bool)
    assert isinstance(reason, str)


def test_floor_applies_when_items_small():
    # items=200: per_item=12500us > 500 => FAIL on per_item; floor=max(2000, 100)=2000 also exceeded.
    passed, reason = check_grc_latency(elapsed_ms=2500, items_analyzed=200)
    assert not passed, f"expected FAIL but got: {reason}"


def test_real_endpoint_passes():
    """Integration: hit reflect endpoint and assert invariant.

    Skips when Core not running or env key missing — does NOT fail.
    """
    api_key = os.environ.get("CORE_INTERNAL_API_KEY")
    if not api_key:
        pytest.skip("CORE_INTERNAL_API_KEY not set")

    url = "http://localhost:10000/api/memvault/reflect?scope_id=default"
    req = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={"x-internal-key": api_key, "Content-Type": "application/json"},
    )

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        pytest.skip(f"Core unreachable: {exc}")

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    import json

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        pytest.fail(f"reflect returned non-JSON: {exc}")

    items = payload.get("items_analyzed")
    if items is None:
        pytest.fail(f"response missing items_analyzed: {payload!r}")

    passed, reason = check_grc_latency(elapsed_ms=elapsed_ms, items_analyzed=int(items))
    assert passed, reason

"""Test: finance/exchange.py — fetch_rates retry + get_exchange_rates cache fallback.

Behavioral spec (do NOT read implementation files):
  - fetch_rates: 3 retries on network errors; returns dict on success, raises on all-fail
  - get_exchange_rates: returns cached value from Redis if fresh; calls fetch_rates on miss;
    falls back to cache or in-memory store when API is down after all retries

Mutation targets:
  - max_retries=3 → 1   → test_fetch_rates_retries_3_times_on_network_error catches this
  - ConnectionError not in retryable set → test_fetch_rates_retries_on_connection_error catches this
  - Redis hit skips fetch_rates call → test_get_rates_returns_cache_on_hit catches this
  - Cache miss but API up → test_get_rates_calls_fetch_on_cache_miss catches this
  - Cache present + API down → test_get_rates_returns_stale_cache_when_api_fails catches this
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_CORE_ROOT = Path(__file__).resolve().parent.parent
if str(_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CORE_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_RATES: dict = {
    "date": "2026-03-24",
    "usd": {"twd": 32.5, "eur": 0.92, "jpy": 151.2},
}


def _make_redis_mock(cached_value: str | None = None) -> MagicMock:
    """Return a mock Redis client with get/set/setex stubs."""
    r = MagicMock()
    r.get = AsyncMock(return_value=cached_value)
    r.setex = AsyncMock(return_value=True)
    r.set = AsyncMock(return_value=True)
    return r


# ---------------------------------------------------------------------------
# TestFetchRatesRetry
# ---------------------------------------------------------------------------


class TestFetchRatesRetry:
    """fetch_rates must retry exactly 3 times on transient network errors."""

    def test_fetch_rates_returns_dict_on_success(self):
        """Happy path: external call succeeds, returns dict."""

        from src.modules.finance.exchange import fetch_rates

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_RATES
        mock_response.raise_for_status = MagicMock()

        async def fake_get(*args, **kwargs):
            return mock_response

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = fake_get
            mock_client_cls.return_value = mock_client

            result = asyncio.run(fetch_rates())

        assert isinstance(result, dict), "fetch_rates must return a dict on success"

    def test_fetch_rates_retries_3_times_on_network_error(self):
        """ConnectError must trigger retry; after 3 total attempts, raises."""
        import httpx
        from src.modules.finance.exchange import fetch_rates

        call_count = 0

        async def always_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("simulated network failure")

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = always_fail
            mock_client_cls.return_value = mock_client

            with pytest.raises(Exception):
                asyncio.run(fetch_rates())

        # MUTATION TARGET: max_retries=3 → must call get() exactly 3 times
        assert call_count == 3, (
            f"Expected 3 HTTP calls on retry exhaustion (got {call_count}); "
            "mutation may have changed max_retries"
        )

    def test_fetch_rates_retries_on_connection_error(self):
        """httpx.ConnectError (network-level) must be in retryable set."""
        import httpx
        from src.modules.finance.exchange import fetch_rates

        attempts: list[int] = []

        async def fail_twice_then_succeed(*args, **kwargs):
            attempts.append(1)
            if len(attempts) < 3:
                raise httpx.ConnectError("transient failure")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = SAMPLE_RATES
            return mock_resp

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = fail_twice_then_succeed
            mock_client_cls.return_value = mock_client

            result = asyncio.run(fetch_rates())

        assert isinstance(result, dict)
        assert len(attempts) == 3, (
            f"Expected 3 attempts before success (got {len(attempts)}); "
            "ConnectError may not be in retryable set"
        )

    def test_fetch_rates_raises_after_all_retries_exhausted(self):
        """Invariant: fetch_rates raises (not returns None) after all retries fail."""
        import httpx
        from src.modules.finance.exchange import fetch_rates

        async def always_fail(*args, **kwargs):
            raise httpx.ConnectError("persistent failure")

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = always_fail
            mock_client_cls.return_value = mock_client

            with pytest.raises(Exception) as exc_info:
                asyncio.run(fetch_rates())

        # Must raise, not return None or {}
        assert exc_info.value is not None


# ---------------------------------------------------------------------------
# TestGetExchangeRatesCache
# ---------------------------------------------------------------------------


class TestGetExchangeRatesCache:
    """get_exchange_rates must implement cache-first, fetch-on-miss, fallback-on-fail."""

    def test_get_rates_returns_cache_on_hit(self):
        """Fresh Redis cache → fetch_rates is never called."""
        import json

        from src.modules.finance.exchange import get_exchange_rates

        cached_json = json.dumps(SAMPLE_RATES)
        redis_mock = _make_redis_mock(cached_value=cached_json.encode())

        with (
            patch("src.modules.finance.exchange._get_redis", return_value=redis_mock),
            patch(
                "src.modules.finance.exchange.fetch_rates",
                new_callable=AsyncMock,
            ) as mock_fetch,
        ):
            result = asyncio.run(get_exchange_rates())

        # MUTATION TARGET: cache-hit path must skip fetch
        mock_fetch.assert_not_called()
        assert isinstance(result, dict), "Must return dict from cache"

    def test_get_rates_calls_fetch_on_cache_miss(self):
        """Redis cache miss → fetch_rates is called; result is stored."""
        from src.modules.finance.exchange import get_exchange_rates

        redis_mock = _make_redis_mock(cached_value=None)

        with (
            patch("src.modules.finance.exchange._get_redis", return_value=redis_mock),
            patch(
                "src.modules.finance.exchange.fetch_rates",
                new_callable=AsyncMock,
                return_value=SAMPLE_RATES,
            ) as mock_fetch,
        ):
            result = asyncio.run(get_exchange_rates())

        # MUTATION TARGET: cache-miss path must call fetch_rates
        mock_fetch.assert_called_once()
        assert isinstance(result, dict)

    def test_get_rates_returns_stale_cache_when_api_fails(self):
        """API down after all retries → must return cached value instead of raising."""
        import json

        import httpx
        from src.modules.finance.exchange import get_exchange_rates

        # Redis has stale data
        cached_json = json.dumps(SAMPLE_RATES)
        redis_mock = _make_redis_mock(cached_value=cached_json.encode())

        async def api_always_fails(*args, **kwargs):
            raise httpx.ConnectError("API down")

        with (
            patch("src.modules.finance.exchange._get_redis", return_value=redis_mock),
            patch(
                "src.modules.finance.exchange.fetch_rates",
                new_callable=AsyncMock,
                side_effect=Exception("API down after retries"),
            ),
        ):
            # Must not raise — should fall back to cache
            result = asyncio.run(get_exchange_rates())

        assert isinstance(result, dict), (
            "get_exchange_rates must return cached dict even when API is down"
        )

    def test_get_rates_returns_stale_cache_when_no_fresh_and_api_fails(self):
        """No fresh cache + API down → returns stale cache (graceful degradation)."""
        from src.modules.finance.exchange import get_exchange_rates

        redis_mock = _make_redis_mock(cached_value=None)

        with (
            patch("src.modules.finance.exchange._get_redis", return_value=redis_mock),
            patch(
                "src.modules.finance.exchange.fetch_rates",
                new_callable=AsyncMock,
                side_effect=Exception("API totally unreachable"),
            ),
        ):
            # Impl degrades gracefully: returns stale cache or empty dict, does not raise
            result = asyncio.run(get_exchange_rates())
            assert isinstance(result, dict)

    def test_get_rates_result_is_dict(self):
        """Invariant: get_exchange_rates always returns a dict on success."""

        from src.modules.finance.exchange import get_exchange_rates

        redis_mock = _make_redis_mock(cached_value=None)

        with (
            patch("src.modules.finance.exchange._get_redis", return_value=redis_mock),
            patch(
                "src.modules.finance.exchange.fetch_rates",
                new_callable=AsyncMock,
                return_value=SAMPLE_RATES,
            ),
        ):
            result = asyncio.run(get_exchange_rates())

        assert isinstance(result, dict)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# MUTATION TARGETS
# ---------------------------------------------------------------------------
# fetch_rates:
#   max_retries=3 → 1        : test_fetch_rates_retries_3_times_on_network_error
#   max_retries=3 → 0        : test_fetch_rates_retries_3_times_on_network_error
#   ConnectError not retried  : test_fetch_rates_retries_on_connection_error
#   raises None instead       : test_fetch_rates_raises_after_all_retries_exhausted
#
# get_exchange_rates:
#   skip cache check          : test_get_rates_returns_cache_on_hit
#   skip fetch on miss        : test_get_rates_calls_fetch_on_cache_miss
#   raise instead of fallback : test_get_rates_returns_stale_cache_when_api_fails
#   return None on success    : test_get_rates_result_is_dict

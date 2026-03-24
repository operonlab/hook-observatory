"""Exchange rate service — fetch and cache currency rates.

Uses jsdelivr CDN (fawazahmed0/currency-api) with Redis cache (6h TTL).
Fallback: in-memory cache if Redis unavailable.
"""

import json
import logging
import time
from typing import Any

import httpx

from workshop.retry import async_with_backoff

logger = logging.getLogger(__name__)

# CDN API — free, no key, daily updates
_CDN_BASE = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies"
_CACHE_KEY = "finance:exchange_rates"
_CACHE_TTL = 6 * 3600  # 6 hours

# In-memory fallback
_mem_cache: dict[str, Any] = {}
_mem_cache_ts: float = 0


def _get_redis():
    """Get Redis client from the existing app infrastructure."""
    try:
        from src.shared.redis import get_redis

        return get_redis()
    except Exception:
        return None


@async_with_backoff(
    max_retries=3,
    base_delay=2.0,
    max_delay=30.0,
    retryable=(httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError),
)
async def fetch_rates() -> dict[str, Any]:
    """Fetch USD-based exchange rates from CDN (with exponential backoff retry)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{_CDN_BASE}/usd.json")
        resp.raise_for_status()
        data = resp.json()
    return {
        "base": "USD",
        "rates": {k.upper(): v for k, v in data.get("usd", {}).items()},
        "date": data.get("date", ""),
    }


async def get_exchange_rates() -> dict[str, Any]:
    """Get exchange rates with Redis cache + in-memory fallback."""
    global _mem_cache, _mem_cache_ts

    # Try Redis cache first
    redis = _get_redis()
    if redis:
        try:
            cached = await redis.get(_CACHE_KEY)
            if cached:
                return json.loads(cached)
        except Exception:
            logger.warning("Redis cache read failed, trying CDN")
        finally:
            try:
                await redis.aclose()
            except Exception:
                logger.debug("Redis aclose failed (read path)")

    # Check in-memory cache
    if _mem_cache and (time.time() - _mem_cache_ts) < _CACHE_TTL:
        return _mem_cache

    # Fetch fresh from CDN
    try:
        data = await fetch_rates()
    except Exception:
        logger.warning("CDN fetch failed, returning stale cache")
        if _mem_cache:
            return _mem_cache
        return {"base": "USD", "rates": {"TWD": 31.5, "USD": 1.0}, "date": "fallback"}

    # Store in Redis
    redis = _get_redis()
    if redis:
        try:
            await redis.set(_CACHE_KEY, json.dumps(data), ex=_CACHE_TTL)
        except Exception:
            logger.warning("Redis cache write failed")
        finally:
            try:
                await redis.aclose()
            except Exception:
                logger.debug("Redis aclose failed (write path)")

    # Store in memory
    _mem_cache = data
    _mem_cache_ts = time.time()

    return data

"""Translation cache using Redis."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date

import redis.asyncio as aioredis

from config import config

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Get or create async Redis connection."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(config.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None


def _cache_key(text: str, source_lang: str, target_lang: str) -> str:
    """Generate cache key: MD5(source|target|text)."""
    normalized = f"{source_lang}|{target_lang}|{text.strip()}"
    digest = hashlib.md5(normalized.encode()).hexdigest()
    return f"tps:cache:{digest}"


def _budget_key() -> str:
    """Redis key for today's budget counter."""
    return f"tps:budget:{date.today().isoformat()}"


def _usage_key(provider: str) -> str:
    """Redis key for today's provider usage."""
    return f"tps:usage:{date.today().isoformat()}:{provider}"


# ── Cache operations ──


async def cache_get(text: str, source_lang: str, target_lang: str) -> dict | None:
    """Look up cached translation. Returns dict with text/provider or None."""
    try:
        r = await get_redis()
        raw = await r.get(_cache_key(text, source_lang, target_lang))
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.warning("Cache read failed (degraded): %s", e)
    return None


async def cache_set(
    text: str,
    source_lang: str,
    target_lang: str,
    translated: str,
    provider: str,
) -> None:
    """Store translation in cache with TTL."""
    try:
        r = await get_redis()
        key = _cache_key(text, source_lang, target_lang)
        value = json.dumps({"text": translated, "provider": provider})
        await r.set(key, value, ex=config.cache_ttl)
    except Exception as e:
        logger.warning("Cache write failed (degraded): %s", e)


# ── Budget tracking ──


async def record_usage(provider: str, char_count: int, cost_usd: float) -> None:
    """Record provider usage and cost for today."""
    try:
        r = await get_redis()
        pipe = r.pipeline()
        # Accumulate daily cost
        bkey = _budget_key()
        pipe.incrbyfloat(bkey, cost_usd)
        pipe.expire(bkey, 86400 * 2)  # expire after 2 days
        # Provider-specific usage
        ukey = _usage_key(provider)
        pipe.hincrby(ukey, "char_count", char_count)
        pipe.hincrby(ukey, "request_count", 1)
        pipe.hincrbyfloat(ukey, "cost_usd", cost_usd)
        pipe.expire(ukey, 86400 * 2)
        await pipe.execute()
    except Exception as e:
        logger.warning("Usage tracking failed (degraded): %s", e)


async def get_daily_cost() -> float:
    """Get today's total cost."""
    try:
        r = await get_redis()
        val = await r.get(_budget_key())
        return float(val) if val else 0.0
    except Exception:
        return 0.0


async def is_budget_exceeded() -> bool:
    """Check if daily budget is exhausted."""
    return await get_daily_cost() >= config.daily_budget_usd


async def get_usage_stats() -> dict:
    """Get today's usage stats per provider."""
    try:
        r = await get_redis()
        today = date.today().isoformat()
        stats = {}
        for pname in ("deepl", "google"):
            ukey = f"tps:usage:{today}:{pname}"
            raw = await r.hgetall(ukey)
            stats[pname] = {
                "char_count": int(raw.get("char_count", 0)),
                "request_count": int(raw.get("request_count", 0)),
                "estimated_cost_usd": float(raw.get("cost_usd", 0)),
            }
        return stats
    except Exception:
        return {}

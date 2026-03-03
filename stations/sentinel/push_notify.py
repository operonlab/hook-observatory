"""Publish push notifications via Redis Pub/Sub to Core notification module."""

from __future__ import annotations

import json
import logging
import os

import redis.asyncio as aioredis

logger = logging.getLogger("sentinel.push")

REDIS_URL = os.environ.get("SENTINEL_REDIS_URL", "redis://localhost:6379/0")
CHANNEL = "workshop:push"

_pool: aioredis.ConnectionPool | None = None


def _get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
    return aioredis.Redis(connection_pool=_pool)


async def publish_push(
    *,
    title: str,
    body: str = "",
    category: str = "sentinel",
    severity: str = "warning",
    tag: str | None = None,
    url: str = "/apps/sentinel/",
    user_id: str | None = None,
) -> None:
    """Publish a push notification payload to Redis workshop:push channel."""
    payload = {
        "category": category,
        "title": title,
        "body": body,
        "url": url,
        "tag": tag,
        "severity": severity,
        "user_id": user_id,
    }
    try:
        r = _get_redis()
        await r.publish(CHANNEL, json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        logger.warning("Failed to publish push notification: %s", e)

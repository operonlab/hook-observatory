"""Redis connection pool and dependency."""

import redis.asyncio as aioredis

from src.config import settings

pool = aioredis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


def get_redis() -> aioredis.Redis:
    """Get a Redis client from the connection pool."""
    return aioredis.Redis(connection_pool=pool)

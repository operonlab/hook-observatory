"""Redis connection pool and dependency."""

import redis.asyncio as aioredis

from src.config import settings

pool = aioredis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)

# Binary pool for raw bytes (embedding vectors via struct.pack)
_binary_pool = aioredis.ConnectionPool.from_url(settings.redis_url, decode_responses=False)


def get_redis() -> aioredis.Redis:
    """Get a Redis client from the connection pool."""
    return aioredis.Redis(connection_pool=pool)


def get_redis_binary() -> aioredis.Redis:
    """Get a Redis client that returns raw bytes (for embedding vectors)."""
    return aioredis.Redis(connection_pool=_binary_pool)

"""Database connection pool — asyncpg for workshop PostgreSQL."""

from __future__ import annotations

import asyncpg
import structlog

from agent_metrics.config import settings

log = structlog.get_logger()

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.DATABASE_URL,
            min_size=2,
            max_size=10,
            server_settings={"search_path": "agent_metrics,public"},
        )
        log.info("db_pool_created", dsn=settings.DATABASE_URL.split("@")[-1])
    return _pool


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("db_pool_closed")

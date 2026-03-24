"""Translate Station — PostgreSQL cache + usage tracking."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import config
from models import Base, TranslationCache, UsageLog

logger = logging.getLogger(__name__)

engine = create_async_engine(config.database_url, pool_size=5, max_overflow=5, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create schema + tables if not exist."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS translate"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema ready (translate)")


async def close_db() -> None:
    """Dispose engine connections."""
    await engine.dispose()


def _cache_key(text_: str, source_lang: str, target_lang: str) -> str:
    """Generate MD5 cache key."""
    normalized = f"{source_lang}|{target_lang}|{text_.strip()}"
    return hashlib.md5(normalized.encode()).hexdigest()


# ── Cache operations ──


async def cache_get(text_: str, source_lang: str, target_lang: str) -> dict | None:
    """Look up cached translation within TTL (1 day)."""
    try:
        key = _cache_key(text_, source_lang, target_lang)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=config.cache_ttl)
        async with async_session() as session:
            result = await session.execute(
                select(TranslationCache).where(
                    TranslationCache.cache_key == key,
                    TranslationCache.created_at > cutoff,
                )
            )
            row = result.scalar_one_or_none()
            if row:
                return {"text": row.translated, "provider": row.provider}
    except Exception as e:
        logger.warning("Cache read failed (degraded): %s", e)
    return None


async def cache_set(
    text_: str,
    source_lang: str,
    target_lang: str,
    translated: str,
    provider: str,
    cost_usd: float = 0.0,
) -> None:
    """Store translation in PostgreSQL cache (upsert)."""
    try:
        key = _cache_key(text_, source_lang, target_lang)
        async with async_session() as session:
            stmt = pg_insert(TranslationCache).values(
                cache_key=key,
                source_text=text_,
                translated=translated,
                source_lang=source_lang,
                target_lang=target_lang,
                provider=provider,
                cost_usd=cost_usd,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["cache_key"],
                set_={
                    "translated": translated,
                    "provider": provider,
                    "cost_usd": cost_usd,
                    "created_at": text("now()"),
                },
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as e:
        logger.warning("Cache write failed (degraded): %s", e)


# ── Usage tracking ──


async def record_usage(provider: str, char_count: int, cost_usd: float) -> None:
    """Record provider usage for today (upsert)."""
    try:
        today = date.today()
        async with async_session() as session:
            stmt = pg_insert(UsageLog).values(
                date=today,
                provider=provider,
                char_count=char_count,
                request_count=1,
                cost_usd=cost_usd,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "provider"],
                set_={
                    "char_count": UsageLog.char_count + char_count,
                    "request_count": UsageLog.request_count + 1,
                    "cost_usd": UsageLog.cost_usd + cost_usd,
                },
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as e:
        logger.warning("Usage tracking failed (degraded): %s", e)


async def get_daily_cost() -> float:
    """Get today's total cost across all providers."""
    try:
        today = date.today()
        async with async_session() as session:
            result = await session.execute(
                select(UsageLog.cost_usd).where(UsageLog.date == today)
            )
            return sum(row[0] for row in result.all())
    except Exception:
        return 0.0


async def is_budget_exceeded() -> bool:
    """Check if daily budget is exhausted."""
    return await get_daily_cost() >= config.daily_budget_usd


async def get_usage_stats() -> dict:
    """Get today's usage stats per provider."""
    try:
        today = date.today()
        async with async_session() as session:
            result = await session.execute(
                select(UsageLog).where(UsageLog.date == today)
            )
            stats = {}
            for row in result.scalars().all():
                stats[row.provider] = {
                    "char_count": row.char_count,
                    "request_count": row.request_count,
                    "estimated_cost_usd": row.cost_usd,
                }
            # Ensure both providers appear
            for pname in ("deepl", "google"):
                if pname not in stats:
                    stats[pname] = {
                        "char_count": 0,
                        "request_count": 0,
                        "estimated_cost_usd": 0.0,
                    }
            return stats
    except Exception:
        return {}

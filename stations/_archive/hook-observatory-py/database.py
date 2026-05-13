"""Async database engine + session factory.

Supports PostgreSQL (primary) and SQLite (fallback).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import config

IS_POSTGRES = config.is_postgres

if IS_POSTGRES:
    engine = create_async_engine(
        config.database_url,
        pool_size=5,
        max_overflow=5,
        echo=False,
    )
else:
    # Expand ~ in SQLite path and ensure parent directory exists
    db_url = config.database_url.replace("~", str(Path.home()))
    db_path = db_url.split("///")[-1]
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(db_url, echo=False)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    """FastAPI dependency — yields an async DB session."""
    async with async_session() as session:
        yield session

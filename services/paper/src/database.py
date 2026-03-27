"""Database engine and session management for paper-svc."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

# Convert sync URL to async: postgresql:// → postgresql+psycopg://
_async_url = settings.db_url.replace("postgresql://", "postgresql+psycopg://")

engine = create_async_engine(
    _async_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=5,
    max_overflow=5,
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yield an async DB session."""
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """Verify DB connectivity on startup (no-op if healthy)."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))


async def close_db() -> None:
    """Dispose engine connection pool on shutdown."""
    await engine.dispose()

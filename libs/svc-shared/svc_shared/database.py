"""Database engine and session management for standalone microservices.

Each service provides its own DB URL via config.py; this module handles
engine creation and async session lifecycle.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engine = None
_session_factory = None


def init_db(db_url: str, debug: bool = False) -> None:
    """Initialize the async engine and session factory.

    Called once during app lifespan startup.
    Converts postgresql:// to postgresql+asyncpg:// automatically.
    """
    global _engine, _session_factory

    # Ensure asyncpg driver
    async_url = db_url
    if async_url.startswith("postgresql://"):
        async_url = async_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif async_url.startswith("postgresql+psycopg://"):
        async_url = async_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)

    _engine = create_async_engine(
        async_url,
        echo=debug,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=10,
        max_overflow=10,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def dispose_db() -> None:
    """Dispose the engine connection pool on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def get_db() -> AsyncSession:
    """FastAPI dependency: yield an async DB session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with _session_factory() as session:
        yield session


def get_session_factory() -> async_sessionmaker:
    """Return the session factory for background tasks."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory

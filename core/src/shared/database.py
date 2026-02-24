"""Database engine and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

# Convert sync URL to async (postgresql:// → postgresql+psycopg://)
_async_url = settings.db_url.replace("postgresql://", "postgresql+psycopg://")

engine = create_async_engine(_async_url, echo=settings.debug, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """Dependency: yield an async DB session."""
    async with async_session_factory() as session:
        yield session

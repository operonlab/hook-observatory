"""Database engine and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

# Convert sync URL to async (postgresql:// → postgresql+psycopg://)
_async_url = settings.db_url.replace("postgresql://", "postgresql+psycopg://")

engine = create_async_engine(
    _async_url,
    echo=settings.debug,
    pool_pre_ping=True,  # Fixed in SA 2.0.30+ for psycopg3 async
    pool_recycle=1800,  # Recycle connections every 30 min to avoid AdminShutdown
    pool_size=10,
    max_overflow=10,
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """Dependency: yield an async DB session.

    Adds explicit rollback on cancel/exception. async_session_factory's
    __aexit__ closes the connection but doesn't always rollback an open
    transaction (esp. when the request is cancelled mid-handler), so the
    connection returns to the pool 'idle in transaction' and Postgres
    reports it for hours. Explicit rollback prevents this leak.
    """
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            if session.in_transaction():
                await session.rollback()

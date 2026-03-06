from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

_url = settings.database_url.replace("postgresql://", "postgresql+psycopg://")
engine = create_engine(_url, pool_pre_ping=True, pool_size=5)


@event.listens_for(engine, "connect")
def _set_search_path(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute(f"SET search_path TO {settings.schema_name}, public")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Session:
    return SessionLocal()


def init_db():
    """Create schema if not exists."""
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.schema_name}"))
        conn.commit()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

_url = settings.database_url.replace("postgresql://", "postgresql+psycopg://")
engine = create_engine(
    _url,
    pool_pre_ping=True,
    pool_size=5,
    connect_args={"options": f"-c search_path={settings.schema_name},public"},
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Session:
    return SessionLocal()


def init_db():
    """Create schema if not exists."""
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {settings.schema_name}"))
        conn.commit()

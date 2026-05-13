"""SQLAlchemy models — dialect-agnostic (PostgreSQL / SQLite)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import config

_PG = config.is_postgres


# ── Column types ─────────────────────────────────────────────────

if _PG:
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    _JsonCol = JSONB
    _IdType = PG_UUID(as_uuid=False)
    _id_default = text("gen_random_uuid()")
    _payload_default = text("'{}'::jsonb")
    _ts_default = text("now()")
else:
    _JsonCol = JSON
    _IdType = String(36)
    _id_default = None  # Set in Python via default=
    _payload_default = None
    _ts_default = None


def _make_uuid() -> str:
    from uuid_utils import uuid7

    return str(uuid7())


def _utcnow() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


# ── Table args ───────────────────────────────────────────────────

_base_indexes = (
    Index("idx_events_dedup", "dedup_hash", unique=True),
    Index("idx_events_type", "event_type"),
    Index("idx_events_session", "session_id"),
    Index("idx_events_created", "created_at"),
)

if _PG:
    _table_args = (
        *_base_indexes,
        Index("idx_events_tool", "tool_name", postgresql_where=text("tool_name IS NOT NULL")),
        {"schema": "hook_observatory"},
    )
else:
    _table_args = (
        *_base_indexes,
        Index("idx_events_tool", "tool_name"),
        {},
    )


# ── Model ────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


class HookEvent(Base):
    __tablename__ = "events"
    __table_args__ = _table_args

    id: Mapped[str] = mapped_column(
        _IdType,
        primary_key=True,
        server_default=_id_default,
        default=None if _PG else _make_uuid,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(100))
    cwd: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(100))
    hook_name: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(
        _JsonCol,
        nullable=False,
        server_default=_payload_default,
        default=None if _PG else dict,
    )
    dedup_hash: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=_ts_default,
        default=None if _PG else _utcnow,
    )

"""SQLAlchemy models — hook_observatory schema."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class HookEvent(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("idx_events_dedup", "dedup_hash", unique=True),
        Index("idx_events_type", "event_type"),
        Index("idx_events_session", "session_id"),
        Index("idx_events_created", "created_at"),
        Index("idx_events_tool", "tool_name", postgresql_where=text("tool_name IS NOT NULL")),
        {"schema": "hook_observatory"},
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(100))
    cwd: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(100))
    hook_name: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    dedup_hash: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

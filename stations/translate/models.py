"""Translate Station — SQLAlchemy models."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "translate"


class Base(DeclarativeBase):
    pass


class TranslationCache(Base):
    """Cached translation results (TTL enforced at query time)."""

    __tablename__ = "translation_cache"
    __table_args__ = (
        Index("idx_cache_created", "created_at"),
        {"schema": SCHEMA},
    )

    cache_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_text: Mapped[str] = mapped_column(Text)
    translated: Mapped[str] = mapped_column(Text)
    source_lang: Mapped[str] = mapped_column(String(10))
    target_lang: Mapped[str] = mapped_column(String(10))
    provider: Mapped[str] = mapped_column(String(20))
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class UsageLog(Base):
    """Daily provider usage tracking."""

    __tablename__ = "usage_log"
    __table_args__ = (
        Index("idx_usage_date_provider", "date", "provider", unique=True),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, server_default=text("CURRENT_DATE"))
    provider: Mapped[str] = mapped_column(String(20))
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

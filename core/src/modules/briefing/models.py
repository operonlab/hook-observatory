"""Briefing ORM models — topics, analysts, briefings, entries, follow-ups.

All tables live in the `briefing` PostgreSQL schema.
Migrated from intelflow + new tables for analysts and follow-ups.
"""

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.models import Base, SpaceScopedModel

SCHEMA = "briefing"
EMBEDDING_DIM = 1024  # mlx-embeddings Qwen3-Embedding-0.6B — kept for reference

BRIEFING_STATUSES = (
    "searching",
    "analyzing",
    "debating",
    "synthesizing",
    "completed",
    "failed",
)

ENTRY_PHASES = ("raw", "analysis", "debate", "conclusion")


# ======================== Briefing Topics ========================


class BriefingTopic(SpaceScopedModel):
    """A configurable briefing topic — e.g. tech-trends, weather."""

    __tablename__ = "briefing_topics"
    __table_args__ = (
        Index("idx_bt_name", "space_id", "name", unique=True),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    priority: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    schedule: Mapped[str] = mapped_column(String(20), server_default=text("'daily'"))

    # Relationships
    subtopics: Mapped[list["BriefingSubtopic"]] = relationship(
        back_populates="topic",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


# ======================== Briefing Subtopics ========================


class BriefingSubtopic(SpaceScopedModel):
    """A subtopic within a briefing topic — e.g., weather → Taipei, Tokyo."""

    __tablename__ = "briefing_subtopics"
    __table_args__ = (
        Index("idx_bsub_topic", "topic_id"),
        {"schema": SCHEMA},
    )

    topic_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.briefing_topics.id", ondelete="CASCADE"),
    )
    name: Mapped[str] = mapped_column(Text)
    parameters: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    # Relationships
    topic: Mapped["BriefingTopic"] = relationship(back_populates="subtopics")


# ======================== Briefing Analysts ========================


class BriefingAnalyst(SpaceScopedModel):
    """Configurable analyst persona for multi-analyst debate."""

    __tablename__ = "briefing_analysts"
    __table_args__ = (
        Index("idx_ba_name", "space_id", "name", unique=True),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(String(50))
    display_name: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(7), server_default=text("'#c4a7e7'"))
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    priority: Mapped[int] = mapped_column(Integer, server_default=text("0"))


# ======================== Briefings ========================


class Briefing(SpaceScopedModel):
    """A daily intelligence briefing — one per date per topic."""

    __tablename__ = "briefings"
    __table_args__ = (
        UniqueConstraint("date", "topic_id", name="uq_briefing_date_topic"),
        Index("idx_briefings_date", "date"),
        Index("idx_briefings_topic", "topic_id"),
        {"schema": SCHEMA},
    )

    date: Mapped[str] = mapped_column(Date)
    topic_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.briefing_topics.id"),
        nullable=True,
    )
    domain: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'searching'"))
    # Legacy JSONB fields — kept nullable for migration
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    analyses: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    debate: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    topic: Mapped["BriefingTopic | None"] = relationship(lazy="selectin")
    entries: Mapped[list["BriefingEntry"]] = relationship(
        back_populates="briefing",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    follow_ups: Mapped[list["BriefingFollowUp"]] = relationship(
        back_populates="briefing",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


# ======================== Briefing Entries ========================


class BriefingEntry(SpaceScopedModel):
    """A single entry in a briefing — one per phase per key.

    phase: raw | analysis | debate | conclusion
    key: topic slug (e.g. "finance") or analyst name (e.g. "claude") or "synthesis"
    """

    __tablename__ = "briefing_entries"
    __table_args__ = (
        Index("idx_be_briefing", "briefing_id"),
        Index("idx_be_phase", "phase"),
        UniqueConstraint("briefing_id", "phase", "key", name="uq_be_briefing_phase_key"),
        {"schema": SCHEMA},
    )

    briefing_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.briefings.id", ondelete="CASCADE"),
    )
    phase: Mapped[str] = mapped_column(String(20))
    key: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))

    # Relationships
    briefing: Mapped["Briefing"] = relationship(back_populates="entries")


# ======================== Briefing Follow-Ups ========================


class BriefingFollowUp(SpaceScopedModel):
    """User follow-up question on a briefing conclusion."""

    __tablename__ = "briefing_follow_ups"
    __table_args__ = (
        Index("idx_bfu_briefing", "briefing_id"),
        Index("idx_bfu_created", "created_at"),
        {"schema": SCHEMA},
    )

    briefing_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.briefings.id", ondelete="CASCADE"),
    )
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'pending'"))
    meta: Mapped[dict | None] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))

    # Relationships
    briefing: Mapped["Briefing"] = relationship(back_populates="follow_ups")


# ======================== Archive Tables ========================


class BriefingArchive(Base):
    """Archived briefing — cold data with metadata preserved, vector removed."""

    __tablename__ = "briefings_archive"
    __table_args__ = (
        Index("idx_bra_date", "date"),
        Index("idx_bra_archived", "archived_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)
    date: Mapped[str] = mapped_column(Date)
    domain: Mapped[str] = mapped_column(Text)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    analyses: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    debate: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[str] = mapped_column(Text)
    archive_type: Mapped[str] = mapped_column(String(20), server_default=text("'cold-archive'"))


# ======================== Frozen Tables ========================


class BriefingFrozen(Base):
    """Frozen briefing — minimal metadata in PG, full content in S3."""

    __tablename__ = "briefings_frozen"
    __table_args__ = (
        Index("idx_brf_date", "date"),
        Index("idx_brf_frozen", "frozen_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(Text)
    archived_at: Mapped[str] = mapped_column(Text)
    frozen_at: Mapped[str] = mapped_column(Text)
    date: Mapped[str | None] = mapped_column(Date, nullable=True)
    domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_uri: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

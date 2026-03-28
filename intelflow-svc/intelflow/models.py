"""Intelflow ORM models — reports, topics, search sessions.

All tables live in the `intelflow` PostgreSQL schema.

Standalone variant:
- Archive/frozen models removed (depend on S3/RustFS)
- Embedding columns removed (depend on Qdrant/pgvector)
"""

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models import Base, SpaceScopedModel

SCHEMA = "intelflow"


# ======================== Reports ========================


class Report(SpaceScopedModel):
    """A search/research report — produced by smart-search, company-intel, etc."""

    __tablename__ = "reports"
    __table_args__ = (
        Index("idx_reports_tags", "tags", postgresql_using="gin"),
        Index("idx_reports_created", "created_at"),
        {"schema": SCHEMA},
    )

    title: Mapped[str] = mapped_column(Text)
    query: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    skill_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    topics: Mapped[list["Topic"]] = relationship(
        secondary=f"{SCHEMA}.report_topics",
        back_populates="reports",
        lazy="selectin",
    )


# ======================== Topics ========================


class Topic(SpaceScopedModel):
    """A topic/category — extracted from reports or manually created."""

    __tablename__ = "topics"
    __table_args__ = (
        Index("idx_topics_name", "space_id", "name", unique=True),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    # Relationships
    reports: Mapped[list["Report"]] = relationship(
        secondary=f"{SCHEMA}.report_topics",
        back_populates="topics",
        lazy="selectin",
    )


# ======================== Report-Topic M2M ========================


class ReportTopic(Base):
    """Many-to-many link between reports and topics."""

    __tablename__ = "report_topics"
    __table_args__ = ({"schema": SCHEMA},)

    report_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.reports.id", ondelete="CASCADE"),
        primary_key=True,
    )
    topic_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.topics.id", ondelete="CASCADE"),
        primary_key=True,
    )
    relevance: Mapped[float] = mapped_column(Float, server_default=text("1.0"))


# ======================== Topic Relations ========================


class TopicRelation(Base):
    """Weighted edge between two topics — forms the topic graph."""

    __tablename__ = "topic_relations"
    __table_args__ = ({"schema": SCHEMA},)

    source_topic_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.topics.id", ondelete="CASCADE"),
        primary_key=True,
    )
    target_topic_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.topics.id", ondelete="CASCADE"),
        primary_key=True,
    )
    weight: Mapped[float] = mapped_column(Float, server_default=text("1.0"))


# ======================== Search Sessions ========================


class SearchSession(SpaceScopedModel):
    """A search session — tracks queries and their outcomes."""

    __tablename__ = "search_sessions"
    __table_args__ = ({"schema": SCHEMA},)

    query: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.reports.id", ondelete="SET NULL"),
        nullable=True,
    )

"""Intelflow ORM models — reports, topics, briefings, search sessions.

All tables live in the `intelflow` PostgreSQL schema.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Date,
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

from src.shared.models import Base, SpaceScopedModel

SCHEMA = "intelflow"
EMBEDDING_DIM = 1024  # mlx-embeddings Qwen3-Embedding-0.6B


class ReportEmbedding(Base):
    """Separated embedding vector for Report — allows independent lifecycle management."""

    __tablename__ = "report_embeddings"
    __table_args__ = (
        Index(
            "idx_report_emb_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        {"schema": SCHEMA},
    )

    report_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.reports.id", ondelete="CASCADE"),
        primary_key=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)


# ======================== Reports ========================


class Report(SpaceScopedModel):
    """A search/research report — produced by smart-search, company-intel, etc."""

    __tablename__ = "reports"
    __table_args__ = (
        Index("idx_reports_tags", "tags", postgresql_using="gin"),
        Index("idx_reports_created", "created_at"),
        Index(
            "idx_reports_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "idx_reports_embedding_recent",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("created_at > now() - interval '180 days'"),
        ),
        {"schema": SCHEMA},
    )

    title: Mapped[str] = mapped_column(Text)
    query: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    skill_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

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
        Index(
            "idx_topics_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

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


# ======================== Archive Tables ========================


class ReportArchive(Base):
    """Archived report — cold data with metadata preserved, vector removed.

    Content may be an S3 reference for COLD-BLOB entries (content > 10KB).
    """

    __tablename__ = "reports_archive"
    __table_args__ = (
        Index("idx_ra_tags", "tags", postgresql_using="gin"),
        Index("idx_ra_created", "created_at"),
        Index("idx_ra_archived", "archived_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    query: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)  # may be S3 ref for COLD-BLOB
    sources: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    skill_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[str] = mapped_column(Text)
    archive_type: Mapped[str] = mapped_column(
        String(20), server_default=text("'cold-archive'")
    )  # cold-archive | cold-blob


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
    archive_type: Mapped[str] = mapped_column(
        String(20), server_default=text("'cold-archive'")
    )  # cold-archive | cold-blob


# ======================== Frozen Tables ========================


class ReportFrozen(Base):
    """Frozen report — minimal metadata in PG, full content in S3.

    Legal retention tier. Content is zstd-compressed JSON in
    workshop-frozen bucket.
    """

    __tablename__ = "reports_frozen"
    __table_args__ = (
        Index("idx_rf_space_created", "space_id", "created_at"),
        Index("idx_rf_tags", "tags", postgresql_using="gin"),
        Index("idx_rf_frozen", "frozen_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(Text)
    archived_at: Mapped[str] = mapped_column(Text)
    frozen_at: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_uri: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_size: Mapped[int | None] = mapped_column(Integer, nullable=True)


class BriefingFrozen(Base):
    """Frozen briefing — minimal metadata in PG, full content in S3.

    Legal retention tier. Content is zstd-compressed JSON in
    workshop-frozen bucket.
    """

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

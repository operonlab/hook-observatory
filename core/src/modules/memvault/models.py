"""Memvault ORM models — memory blocks, tags, knowledge domains, profile scores.

All tables live in the `memvault` PostgreSQL schema.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import Base, SpaceScopedModel

SCHEMA = "memvault"
EMBEDDING_DIM = 1024  # mlx-embeddings Qwen3-Embedding-0.6B — kept for services/dedup consumers


class MemoryBlock(SpaceScopedModel):
    """A single memory unit — extracted from sessions, created manually, or imported."""

    __tablename__ = "blocks"
    __table_args__ = (
        Index("idx_blocks_tags", "tags", postgresql_using="gin"),
        Index("idx_blocks_type", "block_type"),
        Index("idx_blocks_session", "source_session"),
        {"schema": SCHEMA},
    )

    source_session: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    block_type: Mapped[str] = mapped_column(
        String(50), server_default=text("'general'")
    )  # knowledge | skill | attitude | general
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # G6: Access tracking — increment on each retrieval for effective half-life computation
    access_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BlockArchive(Base):
    """Archived memory block — cold data with metadata preserved, vector removed.

    Same schema as blocks minus HNSW indexes. Content may be an S3 reference
    for COLD-BLOB entries (content > 10KB).
    """

    __tablename__ = "blocks_archive"
    __table_args__ = (
        Index("idx_ba_tags", "tags", postgresql_using="gin"),
        Index("idx_ba_type", "block_type"),
        Index("idx_ba_created", "created_at"),
        Index("idx_ba_archived", "archived_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(Text)
    source_session: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text)  # may be S3 ref for COLD-BLOB
    block_type: Mapped[str] = mapped_column(String(50))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    archived_at: Mapped[str] = mapped_column(Text)
    archive_type: Mapped[str] = mapped_column(
        String(20), server_default=text("'cold-archive'")
    )  # cold-archive | cold-blob


class Tag(SpaceScopedModel):
    """Aggregated tag index — for efficient listing and autocomplete."""

    __tablename__ = "tags"
    __table_args__ = (
        Index("idx_tags_name", "space_id", "name", unique=True),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(String(200))
    usage_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class KnowledgeDomain(SpaceScopedModel):
    """Knowledge domain aggregate — tracks expertise areas."""

    __tablename__ = "knowledge_domains"
    __table_args__ = (
        Index("idx_kd_name", "space_id", "name", unique=True),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    maturity: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    block_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class ProfileScore(SpaceScopedModel):
    """Profile score — knowledge, attitude, skill aggregate scores."""

    __tablename__ = "profile_scores"
    __table_args__ = (
        Index("idx_profile_scores_space", "space_id", unique=True),
        {"schema": SCHEMA},
    )

    knowledge_score: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    attitude_score: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    skill_score: Mapped[float] = mapped_column(Float, server_default=text("0.0"))


# ======================== Search Feedback ========================


class SearchFeedback(SpaceScopedModel):
    """Explicit relevance feedback on search results — enables closed-loop learning.

    Agents or users can submit positive/negative signals for search results.
    The scoring pipeline aggregates these to boost/penalize future rankings.
    """

    __tablename__ = "search_feedback"
    __table_args__ = (
        Index("idx_sf_entity", "entity_id"),
        Index("idx_sf_query_hash", "query_hash"),
        Index("idx_sf_entity_signal", "entity_id", "signal"),
        {"schema": SCHEMA},
    )

    entity_id: Mapped[str] = mapped_column(String(32))  # block ID that was rated
    query_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 of query text
    signal: Mapped[str] = mapped_column(String(20))  # positive | negative
    feedback_source: Mapped[str] = mapped_column(
        String(20), server_default=text("'agent'")
    )  # agent | user | implicit


# ======================== Frozen Tables ========================


class BlockFrozen(Base):
    """Frozen memory block — minimal metadata in PG, full content in S3.

    Legal retention tier. Content is zstd-compressed JSON in
    workshop-frozen bucket.
    """

    __tablename__ = "blocks_frozen"
    __table_args__ = (
        Index("idx_bf_space_created", "space_id", "created_at"),
        Index("idx_bf_tags", "tags", postgresql_using="gin"),
        Index("idx_bf_frozen", "frozen_at"),
        Index("idx_bf_type", "block_type"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[str] = mapped_column(Text)
    archived_at: Mapped[str] = mapped_column(Text)
    frozen_at: Mapped[str] = mapped_column(Text)
    block_type: Mapped[str] = mapped_column(String(50))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    source_session: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_uri: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

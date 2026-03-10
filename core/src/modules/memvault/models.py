"""Memvault ORM models — memory blocks, tags, knowledge domains, profile scores.

All tables live in the `memvault` PostgreSQL schema.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import Base, SpaceScopedModel

SCHEMA = "memvault"
EMBEDDING_DIM = 1024  # mlx-embeddings Qwen3-Embedding-0.6B


class MemoryBlock(SpaceScopedModel):
    """A single memory unit — extracted from sessions, created manually, or imported."""

    __tablename__ = "blocks"
    __table_args__ = (
        Index("idx_blocks_tags", "tags", postgresql_using="gin"),
        Index("idx_blocks_type", "block_type"),
        Index("idx_blocks_session", "source_session"),
        Index(
            "idx_blocks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "idx_blocks_embedding_recent",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=text("created_at > now() - interval '90 days'"),
        ),
        {"schema": SCHEMA},
    )

    source_session: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    block_type: Mapped[str] = mapped_column(
        String(50), server_default=text("'general'")
    )  # knowledge | skill | attitude | general
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class BlockEmbedding(Base):
    """Separated embedding vector for MemoryBlock — allows independent lifecycle management."""

    __tablename__ = "block_embeddings"
    __table_args__ = (
        Index(
            "idx_block_emb_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        {"schema": SCHEMA},
    )

    block_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.blocks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)


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

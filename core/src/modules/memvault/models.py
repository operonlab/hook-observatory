"""Memvault ORM models — memory blocks, tags, knowledge domains, KAS profiles.

All tables live in the `memvault` PostgreSQL schema.
"""

from sqlalchemy import Float, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from src.shared.models import SpaceScopedModel

SCHEMA = "memvault"
EMBEDDING_DIM = 768  # Ollama nomic-embed-text


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
        {"schema": SCHEMA},
    )

    source_session: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    block_type: Mapped[str] = mapped_column(
        String(50), server_default=text("'general'")
    )  # knowledge | skill | attitude | general
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


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


class KASProfile(SpaceScopedModel):
    """KAS profile — knowledge, attitude, skill scores."""

    __tablename__ = "kas_profiles"
    __table_args__ = (
        Index("idx_kas_space", "space_id", unique=True),
        {"schema": SCHEMA},
    )

    knowledge_score: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    attitude_score: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    skill_score: Mapped[float] = mapped_column(Float, server_default=text("0.0"))

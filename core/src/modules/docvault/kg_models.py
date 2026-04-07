"""DocVault KG ORM models — entities, triples, communities (HiRAG three-layer).

All tables live in the `docvault` PostgreSQL schema.
L0 = entities + triples (chunk-level)
L1 = communities (Leiden clustering)
L2 = community summaries (pre-generated)
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import SpaceScopedModel

SCHEMA = "docvault"


# ======================== L0: Entities ========================


class DocEntity(SpaceScopedModel):
    """Normalized entity node extracted from document chunks."""

    __tablename__ = "doc_entities"
    __table_args__ = (
        Index("idx_docentity_canonical", "space_id", "canonical_name"),
        Index("idx_docentity_document", "document_id"),
        Index("idx_docentity_type", "entity_type"),
        Index("idx_docentity_aliases", "aliases", postgresql_using="gin"),
        {"schema": SCHEMA},
    )

    canonical_name: Mapped[str] = mapped_column(String(500), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    entity_type: Mapped[str] = mapped_column(
        String(50), server_default=text("'concept'")
    )  # concept | person | org | tool | language | location
    document_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_chunk_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )  # chunk IDs that mention this entity
    mention_count: Mapped[int] = mapped_column(Integer, server_default=text("1"))


# ======================== L0: Triples ========================


class DocTriple(SpaceScopedModel):
    """Knowledge triple (SPO) extracted from a document chunk."""

    __tablename__ = "doc_triples"
    __table_args__ = (
        Index("idx_doctriple_subject", "subject"),
        Index("idx_doctriple_predicate", "predicate"),
        Index("idx_doctriple_object", "object"),
        Index("idx_doctriple_document", "document_id"),
        Index("idx_doctriple_chunk", "chunk_id"),
        Index(
            "idx_doctriple_valid",
            "space_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    predicate: Mapped[str] = mapped_column(String(100), nullable=False)
    object: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str | None] = mapped_column(String(500), nullable=True)

    document_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )
    confidence: Mapped[float] = mapped_column(Float, server_default=text("1.0"))

    # Entity resolution (populated by entity dedup)
    subject_entity_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.doc_entities.id", ondelete="SET NULL"),
        nullable=True,
    )
    object_entity_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.doc_entities.id", ondelete="SET NULL"),
        nullable=True,
    )


# ======================== L1: Communities ========================


class DocCommunity(SpaceScopedModel):
    """Leiden community of entities at a specific resolution level."""

    __tablename__ = "doc_communities"
    __table_args__ = (
        Index("idx_doccommunity_level", "resolution_level"),
        Index("idx_doccommunity_parent", "parent_community_id"),
        Index("idx_doccommunity_space", "space_id"),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    resolution_level: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 0=fine, 1=medium, 2=coarse
    size: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    entity_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    top_entities: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    top_predicates: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    parent_community_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.doc_communities.id", ondelete="SET NULL"),
        nullable=True,
    )
    generation_batch: Mapped[str | None] = mapped_column(String(32), nullable=True)
    modularity_score: Mapped[float | None] = mapped_column(Float, nullable=True)


# ======================== L1: Community-Triple M2M ========================


class DocCommunityTriple(SpaceScopedModel):
    """Many-to-many: community ↔ triple membership."""

    __tablename__ = "doc_community_triples"
    __table_args__ = (
        Index("idx_docct_community", "community_id"),
        Index("idx_docct_triple", "triple_id"),
        {"schema": SCHEMA},
    )

    community_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.doc_communities.id", ondelete="CASCADE"),
        nullable=False,
    )
    triple_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.doc_triples.id", ondelete="CASCADE"),
        nullable=False,
    )


# ======================== L2: Community Summaries ========================


class DocCommunitySummary(SpaceScopedModel):
    """Pre-generated LLM summary for a community (L2 layer)."""

    __tablename__ = "doc_community_summaries"
    __table_args__ = (
        Index("idx_doccs_community", "community_id"),
        {"schema": SCHEMA},
    )

    community_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.doc_communities.id", ondelete="CASCADE"),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    key_findings: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    representative_triples: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )  # top 3-5 triple texts
    evidence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generation_batch: Mapped[str | None] = mapped_column(String(32), nullable=True)

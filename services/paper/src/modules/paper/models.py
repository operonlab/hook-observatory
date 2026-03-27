"""Paper ORM models — articles, digests, annotations, citations.

All tables live in the `paper` PostgreSQL schema.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
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

SCHEMA = "paper"
EMBEDDING_DIM = 1024  # mlx-embeddings Qwen3-Embedding-0.6B


# ======================== Article ========================


class Article(SpaceScopedModel):
    """An academic paper — the primary entity of the paper module.

    Supports arXiv papers, DOI-tracked papers, and manually-entered papers.
    HNSW vector index for semantic search (1024d).
    """

    __tablename__ = "articles"
    __table_args__ = (
        Index(
            "idx_articles_arxiv_id",
            "arxiv_id",
            unique=True,
            postgresql_where=text("arxiv_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "idx_articles_doi",
            "doi",
            unique=True,
            postgresql_where=text("doi IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index("idx_articles_tags", "tags", postgresql_using="gin"),
        Index("idx_articles_categories", "categories", postgresql_using="gin"),
        Index("idx_articles_year", "year"),
        Index("idx_articles_created", "created_at"),
        {"schema": SCHEMA},
    )

    # Core metadata
    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(128), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authors: Mapped[list | None] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    journal: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Classification
    categories: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))

    # URLs and storage
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_uri: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Embedding removed — Qdrant handles search vectors

    # Relationships
    digest: Mapped["Digest | None"] = relationship(
        "Digest",
        back_populates="article",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    annotations: Mapped[list["Annotation"]] = relationship(
        "Annotation",
        back_populates="article",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


# ======================== Digest ========================


class Digest(SpaceScopedModel):
    """LLM-generated structured digest for an article.

    1:1 with Article. Records model_used and generated_at for version management.
    Digest version management: model_used + generated_at allow batch redigest
    by model version. Only the latest digest is kept (no history table needed).
    """

    __tablename__ = "digests"
    __table_args__ = (
        Index(
            "idx_digests_paper_id",
            "paper_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_digests_workshop_relevance", "workshop_relevance"),
        Index("idx_digests_model_used", "model_used"),
        {"schema": SCHEMA},
    )

    # Foreign key to article
    paper_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.articles.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Digest content
    one_liner: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_findings: Mapped[list | None] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    workshop_relevance: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )  # high / medium / low
    applicable_modules: Mapped[list | None] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    actionable_insight: Mapped[str | None] = mapped_column(Text, nullable=True)
    effort_estimate: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Quality tracking
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationship
    article: Mapped["Article"] = relationship("Article", back_populates="digest")


# ======================== Annotation ========================


class Annotation(SpaceScopedModel):
    """User annotation on an article — notes, highlights, questions, synthesis, action-taken."""

    __tablename__ = "annotations"
    __table_args__ = (
        Index("idx_annotations_paper_id", "paper_id"),
        Index("idx_annotations_annotation_type", "annotation_type"),
        Index("idx_annotations_tags", "tags", postgresql_using="gin"),
        {"schema": SCHEMA},
    )

    paper_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    annotation_type: Mapped[str] = mapped_column(
        String(32), server_default=text("'note'")
    )  # note / highlight / question / synthesis / action-taken
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))

    # Relationship
    article: Mapped["Article"] = relationship("Article", back_populates="annotations")


# ======================== Citation ========================


class Citation(Base):
    """Citation relationship between two papers.

    Not SpaceScopedModel — citations are global facts, not space-specific.
    """

    __tablename__ = "citations"
    __table_args__ = (
        Index("idx_citations_source", "source_paper_id"),
        Index("idx_citations_target", "target_paper_id"),
        Index(
            "idx_citations_unique",
            "source_paper_id",
            "target_paper_id",
            "relationship_type",
            unique=True,
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_paper_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_paper_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # cites / extends / contradicts / applies

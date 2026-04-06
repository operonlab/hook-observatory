"""DocVault ORM models — documents, versions, chunks, relations, coverage gaps, QA logs.

All tables live in the `docvault` PostgreSQL schema.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.models import SpaceScopedModel

SCHEMA = "docvault"


# ======================== Document ========================


class Document(SpaceScopedModel):
    """A document entity — the primary record of an uploaded file.

    Supports PDF, DOCX, Markdown, HTML, and API-ingested content.
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_tags", "tags", postgresql_using="gin"),
        Index("idx_documents_status", "status"),
        Index("idx_documents_source_type", "source_type"),
        Index(
            "idx_documents_content_hash",
            "content_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_documents_created", "created_at"),
        {"schema": SCHEMA},
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(32), server_default=text("'markdown'")
    )  # pdf | docx | markdown | webpage | api
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256
    current_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata_", JSONB, nullable=True
    )  # author, page_count, language, custom fields
    status: Mapped[str] = mapped_column(
        String(32), server_default=text("'ingested'")
    )  # ingested | processing | indexed | enriched | published | archived | failed
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    versions: Mapped[list["DocumentVersion"]] = relationship(
        "DocumentVersion",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


# ======================== DocumentVersion ========================


class DocumentVersion(SpaceScopedModel):
    """Immutable version snapshot of a document."""

    __tablename__ = "document_versions"
    __table_args__ = (
        Index("idx_docver_document_id", "document_id"),
        Index("idx_docver_status", "status"),
        Index(
            "idx_docver_doc_version",
            "document_id",
            "version_number",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    document_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)  # full text or S3 ref
    status: Mapped[str] = mapped_column(
        String(32), server_default=text("'processing'")
    )  # processing | ready | superseded
    chunk_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    extraction_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    table_of_contents: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # [{title, level, page, chunk_ids}]

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="versions")
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="version",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


# ======================== DocumentChunk ========================


class DocumentChunk(SpaceScopedModel):
    """Semantic segment of a document version."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("idx_chunk_version_id", "version_id"),
        Index("idx_chunk_document_id", "document_id"),
        Index("idx_chunk_doc_index", "document_id", "chunk_index"),
        Index("idx_chunk_section_path", "section_path"),
        {"schema": SCHEMA},
    )

    version_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # denormalized for fast queries
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    section_path: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # "Chapter 3 > 3.2 > Paragraph 4"
    page_range: Mapped[str | None] = mapped_column(String(32), nullable=True)  # "12-13"
    heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    chunk_type: Mapped[str] = mapped_column(
        String(32), server_default=text("'text'")
    )  # text | table | list | code

    # Relationships
    version: Mapped["DocumentVersion"] = relationship("DocumentVersion", back_populates="chunks")


# ======================== DocumentRelation ========================


class DocumentRelation(SpaceScopedModel):
    """Cross-document relationship — citations, extensions, contradictions."""

    __tablename__ = "document_relations"
    __table_args__ = (
        Index("idx_docrel_source", "source_document_id"),
        Index("idx_docrel_target", "target_document_id"),
        Index(
            "idx_docrel_unique",
            "source_document_id",
            "target_document_id",
            "relation_type",
            unique=True,
            postgresql_where=text("invalid_at IS NULL AND deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    source_document_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_document_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # cites | extends | contradicts | supersedes | related
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_chunk_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_by: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # FK → DocumentRelation


# ======================== CoverageGap ========================


class CoverageGap(SpaceScopedModel):
    """Coverage gap tracking — detected when QA pipeline cannot answer confidently."""

    __tablename__ = "coverage_gaps"
    __table_args__ = (
        Index(
            "idx_covgap_query_hash",
            "query_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_covgap_status", "status"),
        {"schema": SCHEMA},
    )

    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gap_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # topic_missing | depth_insufficient | outdated
    status: Mapped[str] = mapped_column(
        String(32), server_default=text("'pending'")
    )  # pending | investigating | resolved | dismissed
    resolution: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # document_added | not_applicable | merged_existing
    resolved_document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    suggested_sources: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # [{url, title, confidence}]


# ======================== QALog ========================


class QALog(SpaceScopedModel):
    """QA log — records every question-answer interaction for analytics."""

    __tablename__ = "qa_logs"
    __table_args__ = (
        Index("idx_qalog_query_hash", "query_hash"),
        Index("idx_qalog_space_created", "space_id", "created_at"),
        Index("idx_qalog_crag_verdict", "crag_verdict"),
        {"schema": SCHEMA},
    )

    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # [{doc_id, chunk_id, section, page, quote}]
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    crag_verdict: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # correct | ambiguous | incorrect
    feedback: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # positive | negative | null
    pipeline_used: Mapped[str] = mapped_column(String(8), server_default=text("'A'"))  # A | B | C
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

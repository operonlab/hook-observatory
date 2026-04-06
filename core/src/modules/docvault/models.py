"""DocVault ORM models — documents, versions, chunks, relations, coverage gaps, QA logs.

All tables live in the `docvault` PostgreSQL schema.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.models import SpaceScopedModel

SCHEMA = "docvault"


class Document(SpaceScopedModel):
    """A document entity — the primary unit of the docvault module."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_doc_tags", "tags", postgresql_using="gin"),
        Index("idx_doc_status", "status"),
        Index("idx_doc_source_type", "source_type"),
        Index(
            "idx_doc_content_hash",
            "content_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(50), server_default=text("'pdf'")
    )  # pdf | docx | markdown | webpage | api
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(30), server_default=text("'ingested'")
    )  # ingested | processing | indexed | enriched | published | archived
    confidence: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    access_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DocumentVersion(SpaceScopedModel):
    """Immutable version snapshot of a document."""

    __tablename__ = "document_versions"
    __table_args__ = (
        Index("idx_dv_document", "document_id"),
        Index("idx_dv_status", "status"),
        {"schema": SCHEMA},
    )

    document_id: Mapped[str] = mapped_column(String(32), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), server_default=text("'processing'")
    )  # processing | ready | superseded
    chunk_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    extraction_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    table_of_contents: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class DocumentChunk(SpaceScopedModel):
    """A semantic segment of a document version."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("idx_dc_document_chunk", "document_id", "chunk_index"),
        Index("idx_dc_version", "version_id"),
        Index("idx_dc_section_path", "section_path"),
        {"schema": SCHEMA},
    )

    version_id: Mapped[str] = mapped_column(String(32), nullable=False)
    document_id: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_range: Mapped[str | None] = mapped_column(String(20), nullable=True)
    heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    chunk_type: Mapped[str] = mapped_column(
        String(30), server_default=text("'text'")
    )  # text | table | list | code


class DocumentRelation(SpaceScopedModel):
    """Relationship between two documents (KG layer)."""

    __tablename__ = "document_relations"
    __table_args__ = (
        Index(
            "idx_dr_unique_active",
            "source_document_id",
            "target_document_id",
            "relation_type",
            unique=True,
            postgresql_where=text("invalid_at IS NULL AND deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    source_document_id: Mapped[str] = mapped_column(String(32), nullable=False)
    target_document_id: Mapped[str] = mapped_column(String(32), nullable=False)
    relation_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # cites | extends | contradicts | supersedes | related
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_chunk_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class CoverageGap(SpaceScopedModel):
    """A detected coverage gap — a query the system cannot answer well."""

    __tablename__ = "coverage_gaps"
    __table_args__ = (
        Index(
            "idx_cg_query_hash",
            "query_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gap_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # topic_missing | depth_insufficient | outdated
    status: Mapped[str] = mapped_column(
        String(30), server_default=text("'pending'")
    )  # pending | investigating | resolved | dismissed
    resolution: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resolved_document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    suggested_sources: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class QALog(SpaceScopedModel):
    """QA session log — tracks questions, answers, and quality metrics."""

    __tablename__ = "qa_logs"
    __table_args__ = (
        Index("idx_qa_query_hash", "query_hash"),
        Index("idx_qa_created", "created_at"),
        {"schema": SCHEMA},
    )

    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, server_default=text("0.0"))
    crag_verdict: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )  # correct | ambiguous | incorrect
    feedback: Mapped[str | None] = mapped_column(String(30), nullable=True)  # positive | negative
    pipeline_used: Mapped[str] = mapped_column(String(10), server_default=text("'A'"))  # A | B | C
    latency_ms: Mapped[int] = mapped_column(Integer, server_default=text("0"))

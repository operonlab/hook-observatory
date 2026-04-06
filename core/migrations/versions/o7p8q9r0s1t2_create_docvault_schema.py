"""Create docvault schema and 6 tables.

Revision ID: o7p8q9r0s1t2
Revises: n6o7p8q9r0s1
Create Date: 2026-04-06
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "o7p8q9r0s1t2"
down_revision = "n6o7p8q9r0s1"
branch_labels = None
depends_on = None

SCHEMA = "docvault"


def upgrade():
    # Create schema
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # 1. documents
    op.create_table(
        "documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(32), server_default=sa.text("'markdown'")),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("current_version_id", sa.String(32), nullable=True),
        sa.Column("tags", ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]")),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("status", sa.String(32), server_default=sa.text("'ingested'")),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("access_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_documents_tags", "documents", ["tags"],
        postgresql_using="gin", schema=SCHEMA,
    )
    op.create_index(
        "idx_documents_status", "documents", ["status"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_documents_source_type", "documents", ["source_type"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_documents_content_hash", "documents", ["content_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_documents_created", "documents", ["created_at"],
        schema=SCHEMA,
    )

    # 2. document_versions
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column(
            "document_id", sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), server_default=sa.text("'processing'")),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("extraction_model", sa.String(128), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("table_of_contents", JSONB, nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_docver_document_id", "document_versions", ["document_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_docver_status", "document_versions", ["status"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_docver_doc_version", "document_versions",
        ["document_id", "version_number"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        schema=SCHEMA,
    )

    # 3. document_chunks
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column(
            "version_id", sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("page_range", sa.String(32), nullable=True),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("token_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("chunk_type", sa.String(32), server_default=sa.text("'text'")),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_chunk_version_id", "document_chunks", ["version_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_chunk_document_id", "document_chunks", ["document_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_chunk_doc_index", "document_chunks",
        ["document_id", "chunk_index"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_chunk_section_path", "document_chunks", ["section_path"],
        schema=SCHEMA,
    )

    # 4. document_relations
    op.create_table(
        "document_relations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column(
            "source_document_id", sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_document_id", sa.String(32),
            sa.ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("source_chunk_id", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_by", sa.String(32), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_docrel_source", "document_relations", ["source_document_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_docrel_target", "document_relations", ["target_document_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_docrel_unique", "document_relations",
        ["source_document_id", "target_document_id", "relation_type"],
        unique=True,
        postgresql_where=sa.text("invalid_at IS NULL AND deleted_at IS NULL"),
        schema=SCHEMA,
    )

    # 5. coverage_gaps
    op.create_table(
        "coverage_gaps",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gap_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default=sa.text("'pending'")),
        sa.Column("resolution", sa.String(32), nullable=True),
        sa.Column("resolved_document_id", sa.String(32), nullable=True),
        sa.Column("suggested_sources", JSONB, nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_covgap_query_hash", "coverage_gaps", ["query_hash"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_covgap_status", "coverage_gaps", ["status"],
        schema=SCHEMA,
    )

    # 6. qa_logs
    op.create_table(
        "qa_logs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("citations", JSONB, nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("crag_verdict", sa.String(32), nullable=True),
        sa.Column("feedback", sa.String(32), nullable=True),
        sa.Column("pipeline_used", sa.String(8), server_default=sa.text("'A'")),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_qalog_query_hash", "qa_logs", ["query_hash"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_qalog_space_created", "qa_logs", ["space_id", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_qalog_crag_verdict", "qa_logs", ["crag_verdict"],
        schema=SCHEMA,
    )


def downgrade():
    op.drop_table("qa_logs", schema=SCHEMA)
    op.drop_table("coverage_gaps", schema=SCHEMA)
    op.drop_table("document_relations", schema=SCHEMA)
    op.drop_table("document_chunks", schema=SCHEMA)
    op.drop_table("document_versions", schema=SCHEMA)
    op.drop_table("documents", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")

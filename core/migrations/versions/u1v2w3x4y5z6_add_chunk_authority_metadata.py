"""Add source_role and doc_weight columns to docvault.document_chunks.

Revision ID: u1v2w3x4y5z6
Revises: s1t2u3v4w5x7
Create Date: 2026-05-19

Phase 1 of authority-aware retrieval. Persists chunk metadata produced
by contextual_chunk.py so jina_rerank can apply doc_weight * role_factor
weighting. Both columns are nullable for back-compat with existing rows
(no backfill — older chunks fall back to defaults in rerank).
"""

import sqlalchemy as sa
from alembic import op

revision = "u1v2w3x4y5z6"
down_revision = "s1t2u3v4w5x7"
branch_labels = None
depends_on = None

SCHEMA = "docvault"


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("source_role", sa.String(32), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "document_chunks",
        sa.Column("doc_weight", sa.Float(), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_chunk_source_role",
        "document_chunks",
        ["source_role"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("idx_chunk_source_role", table_name="document_chunks", schema=SCHEMA)
    op.drop_column("document_chunks", "source_role", schema=SCHEMA)
    op.drop_column("document_chunks", "doc_weight", schema=SCHEMA)

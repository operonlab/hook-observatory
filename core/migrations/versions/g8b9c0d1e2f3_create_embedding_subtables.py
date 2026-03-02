"""create embedding sub-tables for hot/cold vector separation

Separates embedding vectors from main entity tables into dedicated sub-tables:
  - memvault.block_embeddings  (1:1 with blocks)
  - memvault.triple_embeddings (1:1 with triples)
  - intelflow.report_embeddings (1:1 with reports)

Benefits:
  - Vectors can be archived/deleted independently of metadata
  - HNSW indexes are scoped to the sub-table only
  - Metadata queries no longer scan TOAST pages for embeddings

This migration copies existing embeddings from the parent tables into the
sub-tables.  The parent embedding columns are NOT dropped (backward compat);
removal is deferred to a future migration once all queries use the sub-table.

Revision ID: g8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "g8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    # --- memvault.block_embeddings ---
    op.create_table(
        "block_embeddings",
        sa.Column("block_id", sa.String(32), sa.ForeignKey("memvault.blocks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        schema="memvault",
    )
    op.create_index(
        "idx_block_emb_hnsw",
        "block_embeddings",
        ["embedding"],
        schema="memvault",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    # Copy existing embeddings
    op.execute(
        """
        INSERT INTO memvault.block_embeddings (block_id, embedding)
        SELECT id, embedding FROM memvault.blocks
        WHERE embedding IS NOT NULL
        ON CONFLICT DO NOTHING;
        """
    )

    # --- memvault.triple_embeddings ---
    op.create_table(
        "triple_embeddings",
        sa.Column("triple_id", sa.String(32), sa.ForeignKey("memvault.triples.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        schema="memvault",
    )
    op.create_index(
        "idx_triple_emb_hnsw",
        "triple_embeddings",
        ["embedding"],
        schema="memvault",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    # Copy existing embeddings
    op.execute(
        """
        INSERT INTO memvault.triple_embeddings (triple_id, embedding)
        SELECT id, embedding FROM memvault.triples
        WHERE embedding IS NOT NULL
        ON CONFLICT DO NOTHING;
        """
    )

    # --- intelflow.report_embeddings ---
    op.create_table(
        "report_embeddings",
        sa.Column("report_id", sa.String(32), sa.ForeignKey("intelflow.reports.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        schema="intelflow",
    )
    op.create_index(
        "idx_report_emb_hnsw",
        "report_embeddings",
        ["embedding"],
        schema="intelflow",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    # Copy existing embeddings
    op.execute(
        """
        INSERT INTO intelflow.report_embeddings (report_id, embedding)
        SELECT id, embedding FROM intelflow.reports
        WHERE embedding IS NOT NULL
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_table("report_embeddings", schema="intelflow")
    op.drop_table("triple_embeddings", schema="memvault")
    op.drop_table("block_embeddings", schema="memvault")

"""Drop pgvector embedding columns — search migrated to Qdrant.

Revision ID: g9h0i1j2k3l4
Revises: f3g4h5i6j7k8
Create Date: 2026-03-17
"""

from alembic import op

revision = "g9h0i1j2k3l4"
down_revision = "g4h5i6j7k8l9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # memvault: drop embedding subtables (cascade drops indexes)
    op.drop_table("block_embeddings", schema="memvault")
    op.drop_table("triple_embeddings", schema="memvault")

    # memvault: drop backup tables
    op.execute("DROP TABLE IF EXISTS memvault.block_embeddings_backup")
    op.execute("DROP TABLE IF EXISTS memvault.blocks_embedding_backup")

    # memvault: drop inline embedding columns
    op.drop_column("blocks", "embedding", schema="memvault")
    op.drop_column("triples", "embedding", schema="memvault")
    op.drop_column("entity_canonicals", "embedding", schema="memvault")
    op.drop_column("attitude_facts", "embedding", schema="memvault")

    # intelflow: drop embedding subtable + columns
    op.drop_table("report_embeddings", schema="intelflow")
    op.drop_column("reports", "embedding", schema="intelflow")
    op.drop_column("topics", "embedding", schema="intelflow")

    # briefing: drop embedding columns
    op.drop_column("briefings", "embedding", schema="briefing")
    op.drop_column("briefing_entries", "embedding", schema="briefing")

    # paper: drop embedding columns
    op.execute("DROP TABLE IF EXISTS paper.article_embeddings")
    op.execute("ALTER TABLE paper.articles DROP COLUMN IF EXISTS embedding")


def downgrade() -> None:
    # No downgrade — embeddings now live in Qdrant.
    # To restore: re-add Vector columns + run backfill from Qdrant.
    raise NotImplementedError("pgvector columns cannot be restored automatically")

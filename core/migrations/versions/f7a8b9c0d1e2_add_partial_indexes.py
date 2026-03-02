"""add partial indexes for hot data tiering

Partial HNSW indexes on embedding columns restrict vector search to recent
rows, reducing index size and improving scan performance.  A partial B-tree
index on skill_invocations.created_at accelerates recent-activity queries.

NOTE: These indexes use ``now()`` in the WHERE clause.  PostgreSQL evaluates
``now()`` at INSERT time, so *all* newly inserted rows qualify.  To shrink
the index by removing rows that aged out of the window, run periodic
``REINDEX INDEX CONCURRENTLY <index_name>;`` (e.g. weekly via pg_cron).

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-02-28
"""

from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- memvault.blocks: HNSW partial index (90 days) ---
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_blocks_embedding_recent
        ON memvault.blocks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE created_at > now() - interval '90 days';
        """
    )

    # --- memvault.triples: HNSW partial index (90 days) ---
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_triples_embedding_recent
        ON memvault.triples USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE created_at > now() - interval '90 days';
        """
    )

    # --- memvault.skill_invocations: B-tree partial index (30 days) ---
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_skill_invocations_recent
        ON memvault.skill_invocations (created_at)
        WHERE created_at > now() - interval '30 days';
        """
    )

    # --- intelflow.reports: HNSW partial index (180 days) ---
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_reports_embedding_recent
        ON intelflow.reports USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE created_at > now() - interval '180 days';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS intelflow.idx_reports_embedding_recent;")
    op.execute("DROP INDEX IF EXISTS memvault.idx_skill_invocations_recent;")
    op.execute("DROP INDEX IF EXISTS memvault.idx_triples_embedding_recent;")
    op.execute("DROP INDEX IF EXISTS memvault.idx_blocks_embedding_recent;")

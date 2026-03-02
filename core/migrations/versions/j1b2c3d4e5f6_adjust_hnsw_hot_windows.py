"""adjust HNSW partial index windows for four-tier lifecycle

Changes memvault partial HNSW index from 90 days to 14 days
to match the new Hot tier boundary from tier_config.py.

Intelflow stays at 180 days (already matches its Hot tier).

Revision ID: j1b2c3d4e5f6
Revises: h9a0b1c2d3e4
Create Date: 2026-03-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "j1b2c3d4e5f6"
down_revision: str | None = "h9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ensure IMMUTABLE wrapper exists (created in f7a8b9c0d1e2, safe to re-create)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION hot_cutoff(ivl interval)
        RETURNS timestamptz AS $$
            SELECT now() - ivl;
        $$ LANGUAGE sql IMMUTABLE;
        """
    )

    # Drop the old 90-day partial HNSW index on memvault.blocks
    op.execute("DROP INDEX IF EXISTS memvault.idx_blocks_embedding_recent;")

    # Recreate with 14-day window to match Hot tier boundary
    op.execute(
        """
        CREATE INDEX idx_blocks_embedding_recent
        ON memvault.blocks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE created_at > hot_cutoff(interval '14 days');
        """
    )

    # NOTE: After deploying this migration, the index only covers rows
    # inserted after the CREATE INDEX ran.  Rows that age past 14 days
    # remain in the index until a REINDEX is performed.  The lifecycle
    # script runs ``REINDEX INDEX CONCURRENTLY
    # memvault.idx_blocks_embedding_recent;`` on schedule, so no
    # manual action is required.


def downgrade() -> None:
    # Drop the 14-day partial HNSW index
    op.execute("DROP INDEX IF EXISTS memvault.idx_blocks_embedding_recent;")

    # Restore original 90-day window
    op.execute(
        """
        CREATE INDEX idx_blocks_embedding_recent
        ON memvault.blocks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        WHERE created_at > hot_cutoff(interval '90 days');
        """
    )

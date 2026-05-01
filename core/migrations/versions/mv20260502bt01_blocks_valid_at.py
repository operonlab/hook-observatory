"""Add bitemporal valid_at to memvault.blocks (P1).

Bitemporal completion: separates "valid time" (when fact started being true)
from "system time" (when row was inserted, already in created_at). Mirrors
Triple.valid_at (kg_models.py) and follows the Graphiti pattern.

Indexes added (M8 — codex-driven):
  - idx_blocks_valid_at: partial on valid_at IS NOT NULL — supports plain
    `valid_at <= T` lookups (e.g. /admin tooling).
  - idx_blocks_active_eff: functional on COALESCE(valid_at, created_at) for
    rows where deleted_at IS NULL AND invalid_at IS NULL — the hot index for
    `as_of` recall (active_block_filters with as_of=T).

Both indexes are built CONCURRENTLY (no write-lock on the 8K-row table).
This requires the migration to run OUTSIDE a transaction — see
`__init__.py` autocommit_block.

Revision ID: mv20260502bt01
Revises: mv20260411kg01
Create Date: 2026-05-02
"""

import sqlalchemy as sa
from alembic import op

revision = "mv20260502bt01"
down_revision = "mv20260411kg01"
branch_labels = None
depends_on = None

SCHEMA = "memvault"


def upgrade() -> None:
    # ALTER TABLE ADD COLUMN with no default is metadata-only on PG ≥ 11
    # (no table rewrite, no row lock).
    op.add_column(
        "blocks",
        sa.Column("valid_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )

    # Indexes must be CONCURRENT to avoid blocking writes on a live table.
    # Each CREATE INDEX CONCURRENTLY must run outside a transaction.
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_blocks_valid_at "
            f"ON {SCHEMA}.blocks (valid_at) WHERE valid_at IS NOT NULL"
        )
        # Functional index supports as_of recall: the WHERE matches
        # active_block_filters(as_of=T)'s `deleted_at IS NULL AND invalid_at IS NULL`
        # baseline; the indexed expression matches the COALESCE used inside the
        # bitemporal predicate.
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_blocks_active_eff "
            f"ON {SCHEMA}.blocks (COALESCE(valid_at, created_at)) "
            f"WHERE deleted_at IS NULL AND invalid_at IS NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {SCHEMA}.idx_blocks_active_eff")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {SCHEMA}.idx_blocks_valid_at")
    op.drop_column("blocks", "valid_at", schema=SCHEMA)

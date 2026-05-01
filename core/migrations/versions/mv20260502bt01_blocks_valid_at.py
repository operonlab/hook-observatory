"""Add bitemporal valid_at to memvault.blocks (P1).

Bitemporal completion: separates "valid time" (when fact started being true)
from "system time" (when row was inserted, already in created_at). Mirrors
Triple.valid_at (kg_models.py) and follows the Graphiti pattern.

Index added so as-of recall (P2) can efficiently filter by valid_at <= cutoff.

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
    op.add_column(
        "blocks",
        sa.Column("valid_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_blocks_valid_at",
        "blocks",
        ["valid_at"],
        schema=SCHEMA,
        postgresql_where=sa.text("valid_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_blocks_valid_at", table_name="blocks", schema=SCHEMA)
    op.drop_column("blocks", "valid_at", schema=SCHEMA)

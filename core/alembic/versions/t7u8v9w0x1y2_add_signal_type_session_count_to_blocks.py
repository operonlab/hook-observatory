"""Add signal_type and session_count columns to memvault.blocks.

Revision ID: t7u8v9w0x1y2
Revises: s1t2u3v4w5x6
Create Date: 2026-05-06

Dream Phase 2 — Gather Signal expansion.
signal_type tracks the interaction pattern that generated a block:
  correction | preference_confirmed | repeated_pattern | architecture_decision
session_count tracks how many sessions a repeated_pattern cluster has appeared in.
"""

import sqlalchemy as sa
from alembic import op

revision = "t7u8v9w0x1y2"
down_revision = "t1u2v3w4x5y6"
branch_labels = None
depends_on = None

SCHEMA = "memvault"


def upgrade() -> None:
    op.add_column(
        "blocks",
        sa.Column("signal_type", sa.String(50), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "blocks",
        sa.Column(
            "session_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_blocks_signal_type",
        "blocks",
        ["signal_type"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("idx_blocks_signal_type", table_name="blocks", schema=SCHEMA)
    op.drop_column("blocks", "signal_type", schema=SCHEMA)
    op.drop_column("blocks", "session_count", schema=SCHEMA)

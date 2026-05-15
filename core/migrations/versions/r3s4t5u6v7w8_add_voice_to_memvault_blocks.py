"""Add voice (provenance metric) to memvault.blocks.

Revision ID: r3s4t5u6v7w8
Revises: q1r2s3t4u5v6
Create Date: 2026-05-15

Phase 2 — Provenance metric. `voice` records who "spoke" the memory:

  user_lead       — the user articulated it themselves (low echo-chamber risk)
  dialog          — collaboratively constructed across the conversation
  assistant_lead  — the assistant proposed it, user did not refute (high risk)
  unknown         — extractor could not classify

Lets recall scoring downweight assistant_lead memories so memvault doesn't
gradually drift into a Claude-shaped echo chamber of its own suggestions.

PG 11+ ADD COLUMN with default NULL is metadata-only, safe on hot tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "r3s4t5u6v7w8"
down_revision: str | None = "q1r2s3t4u5v6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "memvault"


def upgrade() -> None:
    op.add_column(
        "blocks",
        sa.Column("voice", sa.String(20), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_blocks_voice",
        "blocks",
        ["voice"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("idx_blocks_voice", table_name="blocks", schema=SCHEMA)
    op.drop_column("blocks", "voice", schema=SCHEMA)

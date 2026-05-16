"""Add superseded_by_doc_id to memvault.blocks.

Revision ID: s1t2u3v4w5x7
Revises: r3s4t5u6v7w8
Create Date: 2026-05-16

The existing blocks.superseded_by has a FK to memvault.blocks(id) — meant
for block→block supersedence inside memvault's dream pipeline. Doc-driven
supersedence (Phase 3 supersede_blocks_by_doc) had to encode the doc_id as
a substring of invalidation_reason because the FK rejected non-block IDs.

This migration adds a dedicated nullable VARCHAR(64) column for doc_id
references — no FK because docvault.documents lives in a different module
schema and architecture.md forbids cross-schema FKs. The application
layer treats the value as a soft reference (look up via
docvault.list_documents if needed).

Bench: ALTER TABLE … ADD COLUMN with default NULL is metadata-only in
PG 11+ so safe on hot tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "s1t2u3v4w5x7"
down_revision: str | None = "r3s4t5u6v7w8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "memvault"


def upgrade() -> None:
    op.add_column(
        "blocks",
        sa.Column("superseded_by_doc_id", sa.String(64), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_blocks_superseded_by_doc",
        "blocks",
        ["superseded_by_doc_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_blocks_superseded_by_doc", table_name="blocks", schema=SCHEMA
    )
    op.drop_column("blocks", "superseded_by_doc_id", schema=SCHEMA)

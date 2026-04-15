"""blocks: add temporal validity columns (invalid_at, superseded_by, invalidation_reason)

Mirrors Triple's Graphiti-inspired temporal validity pattern for MemoryBlock.
Also adds same columns to blocks_archive for preservation during archival.

Revision ID: a1b2c3d4e5f6
Revises: z7r8s9t0u1v2
Create Date: 2026-04-09
"""

import sqlalchemy as sa
from alembic import op

revision = "mv20260409tv01"
down_revision = "o7p8q9r0s1t2"
branch_labels = None
depends_on = None

SCHEMA = "memvault"


def upgrade() -> None:
    # blocks table
    op.add_column(
        "blocks", sa.Column("invalid_at", sa.DateTime(timezone=True), nullable=True), schema=SCHEMA
    )
    op.add_column("blocks", sa.Column("superseded_by", sa.String(32), nullable=True), schema=SCHEMA)
    op.add_column(
        "blocks", sa.Column("invalidation_reason", sa.String(200), nullable=True), schema=SCHEMA
    )

    op.create_foreign_key(
        "fk_blocks_superseded_by",
        "blocks",
        "blocks",
        ["superseded_by"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )

    op.create_index(
        "idx_blocks_valid",
        "blocks",
        ["space_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("invalid_at IS NULL"),
    )

    # blocks_archive table (no FK constraint)
    op.add_column("blocks_archive", sa.Column("invalid_at", sa.Text, nullable=True), schema=SCHEMA)
    op.add_column(
        "blocks_archive", sa.Column("superseded_by", sa.String(32), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "blocks_archive",
        sa.Column("invalidation_reason", sa.String(200), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("blocks_archive", "invalidation_reason", schema=SCHEMA)
    op.drop_column("blocks_archive", "superseded_by", schema=SCHEMA)
    op.drop_column("blocks_archive", "invalid_at", schema=SCHEMA)

    op.drop_index("idx_blocks_valid", "blocks", schema=SCHEMA)
    op.drop_constraint("fk_blocks_superseded_by", "blocks", schema=SCHEMA, type_="foreignkey")

    op.drop_column("blocks", "invalidation_reason", schema=SCHEMA)
    op.drop_column("blocks", "superseded_by", schema=SCHEMA)
    op.drop_column("blocks", "invalid_at", schema=SCHEMA)

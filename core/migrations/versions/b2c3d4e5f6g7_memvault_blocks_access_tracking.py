"""add access_count and last_accessed_at to memvault.blocks

G6 Access Tracking — increment on each retrieval for effective half-life computation.

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f7
Create Date: 2026-03-15
"""

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6g7"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None

SCHEMA = "memvault"


def upgrade() -> None:
    op.add_column(
        "blocks",
        sa.Column("access_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        "blocks",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("blocks", "last_accessed_at", schema=SCHEMA)
    op.drop_column("blocks", "access_count", schema=SCHEMA)

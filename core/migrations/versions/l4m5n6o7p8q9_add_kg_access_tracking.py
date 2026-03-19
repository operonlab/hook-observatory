"""add access tracking to triples and communities

Revision ID: l4m5n6o7p8q9
Revises: k3l4m5n6o7p8
Create Date: 2026-03-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "l4m5n6o7p8q9"
down_revision: str | None = "k3l4m5n6o7p8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Triple access tracking
    op.add_column(
        "triples",
        sa.Column("access_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        schema="memvault",
    )
    op.add_column(
        "triples",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        schema="memvault",
    )
    # Community access tracking
    op.add_column(
        "communities",
        sa.Column("access_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        schema="memvault",
    )
    op.add_column(
        "communities",
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        schema="memvault",
    )


def downgrade() -> None:
    op.drop_column("communities", "last_accessed_at", schema="memvault")
    op.drop_column("communities", "access_count", schema="memvault")
    op.drop_column("triples", "last_accessed_at", schema="memvault")
    op.drop_column("triples", "access_count", schema="memvault")

"""add triple display_zh

Revision ID: k3l4m5n6o7p8
Revises: j2k3l4m5n6o7
Create Date: 2026-03-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "k3l4m5n6o7p8"
down_revision: str | None = "j2k3l4m5n6o7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("triples", sa.Column("display_zh", sa.Text(), nullable=True), schema="memvault")


def downgrade() -> None:
    op.drop_column("triples", "display_zh", schema="memvault")

"""add description_zh to memvault communities

Revision ID: j2k3l4m5n6o7
Revises: i1j2k3l4m5n6
Create Date: 2026-03-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j2k3l4m5n6o7"
down_revision: str | Sequence[str] | None = "i1j2k3l4m5n6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "communities",
        sa.Column("description_zh", sa.Text(), nullable=True),
        schema="memvault",
    )


def downgrade() -> None:
    op.drop_column("communities", "description_zh", schema="memvault")

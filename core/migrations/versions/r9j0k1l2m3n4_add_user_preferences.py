"""add user preferences JSONB column

Revision ID: r9j0k1l2m3n4
Revises: q8i9j0k1l2m3
Create Date: 2026-03-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "r9j0k1l2m3n4"
down_revision: str | None = "cf31e3f5dcc3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("preferences", JSONB, server_default="{}", nullable=False),
        schema="auth",
    )


def downgrade() -> None:
    op.drop_column("users", "preferences", schema="auth")

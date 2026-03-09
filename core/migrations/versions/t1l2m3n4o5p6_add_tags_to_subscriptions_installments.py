"""add tags column to subscriptions and installment_plans

Revision ID: t1l2m3n4o5p6
Revises: s0k1l2m3n4o5
Create Date: 2026-03-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

# revision identifiers, used by Alembic.
revision: str = "t1l2m3n4o5p6"
down_revision: str | None = "s0k1l2m3n4o5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "finance"


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("tags", ARRAY(sa.Text), server_default=sa.text("'{}'::text[]"), nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        "installment_plans",
        sa.Column("tags", ARRAY(sa.Text), server_default=sa.text("'{}'::text[]"), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("installment_plans", "tags", schema=SCHEMA)
    op.drop_column("subscriptions", "tags", schema=SCHEMA)

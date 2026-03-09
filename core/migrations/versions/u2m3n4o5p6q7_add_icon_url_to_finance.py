"""add icon_url to transactions, subscriptions, installment_plans

Revision ID: u2m3n4o5p6q7
Revises: t1l2m3n4o5p6
Create Date: 2026-03-07
"""

import sqlalchemy as sa
from alembic import op

revision = "u2m3n4o5p6q7"
down_revision = "t1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("icon_url", sa.Text(), nullable=True), schema="finance")
    op.add_column(
        "subscriptions", sa.Column("icon_url", sa.Text(), nullable=True), schema="finance"
    )
    op.add_column(
        "installment_plans", sa.Column("icon_url", sa.Text(), nullable=True), schema="finance"
    )


def downgrade() -> None:
    op.drop_column("installment_plans", "icon_url", schema="finance")
    op.drop_column("subscriptions", "icon_url", schema="finance")
    op.drop_column("transactions", "icon_url", schema="finance")

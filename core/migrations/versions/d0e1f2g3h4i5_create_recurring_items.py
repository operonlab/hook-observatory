"""create dailyos recurring_items table

Revision ID: d0e1f2g3h4i5
Revises: c9d0e1f2g3h4
Create Date: 2026-03-08
"""

import sqlalchemy as sa
from alembic import op

revision = "d0e1f2g3h4i5"
down_revision = "c9d0e1f2g3h4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recurring_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("recurrence_type", sa.Text, nullable=False),  # daily, weekly, monthly
        sa.Column("day_of_week", sa.Integer, nullable=True),  # 0=Mon..6=Sun
        sa.Column("day_of_month", sa.Integer, nullable=True),  # 1-31
        sa.Column("start_time", sa.Text, nullable=True),  # HH:MM
        sa.Column("end_time", sa.Text, nullable=True),  # HH:MM
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="dailyos",
    )

    op.create_index("idx_ri_space", "recurring_items", ["space_id"], schema="dailyos")
    op.create_index("idx_ri_active", "recurring_items", ["space_id", "is_active"], schema="dailyos")


def downgrade() -> None:
    op.drop_index("idx_ri_active", table_name="recurring_items", schema="dailyos")
    op.drop_index("idx_ri_space", table_name="recurring_items", schema="dailyos")
    op.drop_table("recurring_items", schema="dailyos")

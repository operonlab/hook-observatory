"""create dailyos activity_spans table

Revision ID: e2f3g4h5i6j7
Revises: b2c3d4e5f6g7
Create Date: 2026-03-16
"""

import sqlalchemy as sa
from alembic import op

revision = "e2f3g4h5i6j7"
down_revision = "b2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_spans",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),  # inclusive
        sa.Column("category", sa.Text, nullable=True),
        sa.Column("color", sa.Text, server_default=sa.text("'#89b4fa'")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="dailyos",
    )

    op.create_index("idx_as_space", "activity_spans", ["space_id"], schema="dailyos")
    op.create_index(
        "idx_as_date_range",
        "activity_spans",
        ["space_id", "start_date", "end_date"],
        schema="dailyos",
    )


def downgrade() -> None:
    op.drop_index("idx_as_date_range", table_name="activity_spans", schema="dailyos")
    op.drop_index("idx_as_space", table_name="activity_spans", schema="dailyos")
    op.drop_table("activity_spans", schema="dailyos")

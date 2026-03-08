"""create dailyos schema and tables

Revision ID: y6q7r8s9t0u1
Revises: x5p6q7r8s9t0
Create Date: 2026-03-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "y6q7r8s9t0u1"
down_revision = "x5p6q7r8s9t0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS dailyos")

    # methods table
    op.create_table(
        "methods",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("name_zh", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("icon", sa.Text, nullable=True),
        sa.Column("color", sa.Text, nullable=True),
        sa.Column("is_preset", sa.Boolean, server_default=sa.text("false")),
        sa.Column(
            "cloned_from_id",
            sa.String(32),
            sa.ForeignKey("dailyos.methods.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("version", sa.Integer, server_default=sa.text("1")),
        sa.Column("layout_type", sa.Text, nullable=False, server_default=sa.text("'list'")),
        sa.Column("tags", ARRAY(sa.Text), nullable=True),
        schema="dailyos",
    )
    op.create_index("idx_method_space", "methods", ["space_id"], schema="dailyos")
    op.create_index(
        "idx_method_unique_slug",
        "methods",
        ["space_id", "slug"],
        unique=True,
        schema="dailyos",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # method_selections table
    op.create_table(
        "method_selections",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "method_id",
            sa.String(32),
            sa.ForeignKey("dailyos.methods.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("context", sa.Text, nullable=False, server_default=sa.text("'default'")),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("overrides", JSONB, nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        schema="dailyos",
    )
    op.create_index(
        "idx_ms_unique_active",
        "method_selections",
        ["space_id", "context"],
        unique=True,
        schema="dailyos",
        postgresql_where=sa.text("deleted_at IS NULL AND is_active = true"),
    )

    # daily_plans table
    op.create_table(
        "daily_plans",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("plan_date", sa.Date, nullable=False),
        sa.Column("context", sa.Text, server_default=sa.text("'default'")),
        sa.Column(
            "method_selection_id",
            sa.String(32),
            sa.ForeignKey("dailyos.method_selections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text, server_default=sa.text("'planning'")),
        sa.Column("items", JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("method_state", JSONB, nullable=True),
        sa.Column("reflection", sa.Text, nullable=True),
        sa.Column("completion_score", sa.Float, nullable=True),
        schema="dailyos",
    )
    op.create_index(
        "idx_dp_unique_date",
        "daily_plans",
        ["space_id", "plan_date", "context"],
        unique=True,
        schema="dailyos",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("daily_plans", schema="dailyos")
    op.drop_table("method_selections", schema="dailyos")
    op.drop_table("methods", schema="dailyos")
    op.execute("DROP SCHEMA IF EXISTS dailyos")

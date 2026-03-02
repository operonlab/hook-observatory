"""create sentinel schema for health monitoring

Creates the sentinel schema with 4 tables:
  - sentinel.health_checks    (individual check results)
  - sentinel.incidents         (incident tracking)
  - sentinel.active_operations (agent operation tracking)
  - sentinel.subscriptions     (webhook subscriptions)

Revision ID: i0a1b2c3d4e5
Revises: h9a0b1c2d3e4
Create Date: 2026-03-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "i0a1b2c3d4e5"
down_revision = "h9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create schema
    op.execute("CREATE SCHEMA IF NOT EXISTS sentinel")

    # --- sentinel.health_checks ---
    op.create_table(
        "health_checks",
        sa.Column(
            "id", sa.String(36), primary_key=True, server_default=sa.text("gen_random_uuid()::text")
        ),
        sa.Column("service", sa.String(50), nullable=False),
        sa.Column("check_type", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("response_ms", sa.Float, nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.String(30), nullable=False, server_default=sa.text("now()::text")
        ),
        schema="sentinel",
    )
    op.create_index("idx_hc_service", "health_checks", ["service"], schema="sentinel")
    op.create_index("idx_hc_created", "health_checks", ["created_at"], schema="sentinel")
    op.create_index("idx_hc_status", "health_checks", ["status"], schema="sentinel")

    # --- sentinel.incidents ---
    op.create_table(
        "incidents",
        sa.Column(
            "id", sa.String(36), primary_key=True, server_default=sa.text("gen_random_uuid()::text")
        ),
        sa.Column("service", sa.String(50), nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default=sa.text("'investigating'")
        ),
        sa.Column("severity", sa.String(20), nullable=False, server_default=sa.text("'minor'")),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("diagnosis", JSONB, nullable=True),
        sa.Column("repair_result", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.String(30), nullable=False, server_default=sa.text("now()::text")
        ),
        sa.Column("resolved_at", sa.String(30), nullable=True),
        schema="sentinel",
    )
    op.create_index("idx_inc_service", "incidents", ["service"], schema="sentinel")
    op.create_index("idx_inc_status", "incidents", ["status"], schema="sentinel")
    op.create_index("idx_inc_created", "incidents", ["created_at"], schema="sentinel")

    # --- sentinel.active_operations ---
    op.create_table(
        "active_operations",
        sa.Column(
            "id", sa.String(36), primary_key=True, server_default=sa.text("gen_random_uuid()::text")
        ),
        sa.Column("service", sa.String(50), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("pid", sa.Integer, nullable=True),
        sa.Column("estimated_duration", sa.Integer, nullable=False, server_default=sa.text("300")),
        sa.Column(
            "created_at", sa.String(30), nullable=False, server_default=sa.text("now()::text")
        ),
        sa.Column("resolved_at", sa.String(30), nullable=True),
        sa.Column("result", sa.String(20), nullable=True),
        schema="sentinel",
    )
    op.create_index("idx_ao_service", "active_operations", ["service"], schema="sentinel")
    op.create_index("idx_ao_agent", "active_operations", ["agent_id"], schema="sentinel")

    # --- sentinel.subscriptions ---
    op.create_table(
        "subscriptions",
        sa.Column(
            "id", sa.String(36), primary_key=True, server_default=sa.text("gen_random_uuid()::text")
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("events", JSONB, nullable=False, server_default=sa.text("'[\"*\"]'::jsonb")),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.String(30), nullable=False, server_default=sa.text("now()::text")
        ),
        schema="sentinel",
    )
    op.create_index("idx_sub_active", "subscriptions", ["active"], schema="sentinel")


def downgrade() -> None:
    op.drop_table("subscriptions", schema="sentinel")
    op.drop_table("active_operations", schema="sentinel")
    op.drop_table("incidents", schema="sentinel")
    op.drop_table("health_checks", schema="sentinel")
    op.execute("DROP SCHEMA IF EXISTS sentinel")

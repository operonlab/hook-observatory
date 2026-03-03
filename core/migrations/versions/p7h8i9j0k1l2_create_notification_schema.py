"""create notification schema

Revision ID: p7h8i9j0k1l2
Revises: o6g7h8i9j0k1
Create Date: 2026-03-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "p7h8i9j0k1l2"
down_revision: str | None = "o6g7h8i9j0k1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_PREFERENCES = '{"sentinel":true,"system":true,"finance":true,"taskflow":true,"intelflow":true,"agent":true}'


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS notification")

    # PushSubscription — one row per browser endpoint
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("app_scope", sa.String(100), server_default="'/v2/'"),
        sa.Column("active", sa.Boolean(), server_default="true"),
        sa.Column("preferences", JSONB(), server_default=f"'{DEFAULT_PREFERENCES}'"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        schema="notification",
    )
    op.create_index(
        "idx_push_sub_user",
        "push_subscriptions",
        ["user_id"],
        schema="notification",
    )
    op.create_index(
        "idx_push_sub_active",
        "push_subscriptions",
        ["active"],
        schema="notification",
    )

    # NotificationLog — delivery records
    op.create_table(
        "notification_log",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), server_default="''"),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("recipients", sa.Integer(), server_default="0"),
        sa.Column("delivered", sa.Integer(), server_default="0"),
        sa.Column("failed", sa.Integer(), server_default="0"),
        sa.Column("source_event", sa.String(100), nullable=True),
        sa.Column("source_data", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        schema="notification",
    )
    op.create_index(
        "idx_notif_log_user",
        "notification_log",
        ["user_id"],
        schema="notification",
    )
    op.create_index(
        "idx_notif_log_category",
        "notification_log",
        ["category"],
        schema="notification",
    )


def downgrade() -> None:
    op.drop_table("notification_log", schema="notification")
    op.drop_table("push_subscriptions", schema="notification")
    op.execute("DROP SCHEMA IF EXISTS notification")

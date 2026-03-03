"""create auth schema

Revision ID: a1b2c3d4e5f6
Revises: 2bb21e53cb53
Create Date: 2026-02-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "2bb21e53cb53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create auth schema
    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    # Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("password_salt", sa.Text, nullable=False),
        sa.Column("role", sa.String(50), server_default="user", nullable=False),
        sa.Column("status", sa.String(50), server_default="active", nullable=False),
        schema="auth",
    )

    # Unique index on email
    op.create_index(
        "idx_users_email",
        "users",
        ["email"],
        unique=True,
        schema="auth",
    )


def downgrade() -> None:
    op.drop_index("idx_users_email", table_name="users", schema="auth")
    op.drop_table("users", schema="auth")
    op.execute("DROP SCHEMA IF EXISTS auth")

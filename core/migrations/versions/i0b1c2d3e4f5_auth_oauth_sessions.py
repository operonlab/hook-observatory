"""auth oauth sessions

Revision ID: i0b1c2d3e4f5
Revises: h9a0b1c2d3e4
Create Date: 2026-03-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "i0b1c2d3e4f5"
down_revision: str | None = "h9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- ALTER auth.users ---
    # Add new columns
    op.add_column(
        "users", sa.Column("display_name", sa.String(100), nullable=True), schema="auth"
    )
    op.add_column("users", sa.Column("avatar_url", sa.Text, nullable=True), schema="auth")

    # Copy name → display_name, then drop name + password_salt
    op.execute("UPDATE auth.users SET display_name = name WHERE display_name IS NULL")
    op.execute("ALTER TABLE auth.users ALTER COLUMN display_name SET NOT NULL")
    op.drop_column("users", "name", schema="auth")
    op.drop_column("users", "password_salt", schema="auth")

    # password_hash → nullable (OAuth-only users have no password)
    op.alter_column("users", "password_hash", nullable=True, schema="auth")

    # status default → 'pending'
    op.alter_column(
        "users",
        "status",
        server_default="pending",
        schema="auth",
    )

    # --- CREATE auth.oauth_accounts ---
    user_fk = sa.ForeignKey("auth.users.id", ondelete="CASCADE")
    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("user_id", sa.String(32), user_fk, nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("avatar_url", sa.Text, nullable=True),
        sa.Column("raw_data", sa.dialects.postgresql.JSONB, nullable=True),
        sa.UniqueConstraint("provider", "provider_id", name="uq_oauth_provider_id"),
        schema="auth",
    )
    op.create_index("idx_oauth_user", "oauth_accounts", ["user_id"], schema="auth")

    # --- CREATE auth.sessions ---
    session_fk = sa.ForeignKey("auth.users.id", ondelete="CASCADE")
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("user_id", sa.String(32), session_fk, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema="auth",
    )
    op.create_index("idx_sessions_user", "sessions", ["user_id"], schema="auth")
    op.create_index(
        "idx_sessions_token", "sessions", ["token_hash"], unique=True, schema="auth"
    )


def downgrade() -> None:
    # Drop new tables
    op.drop_index("idx_sessions_token", table_name="sessions", schema="auth")
    op.drop_index("idx_sessions_user", table_name="sessions", schema="auth")
    op.drop_table("sessions", schema="auth")

    op.drop_index("idx_oauth_user", table_name="oauth_accounts", schema="auth")
    op.drop_table("oauth_accounts", schema="auth")

    # Revert users table
    op.alter_column(
        "users",
        "status",
        server_default="active",
        schema="auth",
    )
    op.alter_column("users", "password_hash", nullable=False, schema="auth")
    op.add_column(
        "users", sa.Column("password_salt", sa.Text, nullable=True), schema="auth"
    )
    op.add_column(
        "users", sa.Column("name", sa.String(100), nullable=True), schema="auth"
    )
    op.execute("UPDATE auth.users SET name = display_name WHERE name IS NULL")
    op.execute("ALTER TABLE auth.users ALTER COLUMN name SET NOT NULL")
    op.drop_column("users", "avatar_url", schema="auth")
    op.drop_column("users", "display_name", schema="auth")

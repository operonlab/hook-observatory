"""create shared.captures table for capture pipeline

Revision ID: w4o5p6q7r8s9
Revises: v3n4o5p6q7r8
Create Date: 2026-03-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w4o5p6q7r8s9"
down_revision: str | None = "v3n4o5p6q7r8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS shared")
    op.create_table(
        "captures",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False, index=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("module", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("raw_input", sa.Text(), nullable=True),
        sa.Column("completeness", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("promoted_id", sa.String(32), nullable=True),
        sa.Column(
            "promoted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            index=True,
        ),
        schema="shared",
    )
    # Index for common queries
    op.create_index(
        "ix_captures_module_status",
        "captures",
        ["module", "status"],
        schema="shared",
    )
    op.create_index(
        "ix_captures_expires_at",
        "captures",
        ["expires_at"],
        schema="shared",
        postgresql_where=sa.text("expires_at IS NOT NULL AND status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_captures_expires_at", table_name="captures", schema="shared")
    op.drop_index("ix_captures_module_status", table_name="captures", schema="shared")
    op.drop_table("captures", schema="shared")

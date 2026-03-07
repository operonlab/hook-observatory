"""add capture enrichments table + version/group_id columns

Revision ID: x5p6q7r8s9t0
Revises: w4o5p6q7r8s9
Create Date: 2026-03-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "x5p6q7r8s9t0"
down_revision: str | None = "w4o5p6q7r8s9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add version + group_id to captures
    op.add_column(
        "captures",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        schema="shared",
    )
    op.add_column(
        "captures",
        sa.Column("group_id", sa.String(32), nullable=True),
        schema="shared",
    )
    op.create_index(
        "ix_captures_group_id",
        "captures",
        ["group_id"],
        schema="shared",
        postgresql_where=sa.text("group_id IS NOT NULL"),
    )

    # Create enrichment history table
    op.create_table(
        "capture_enrichments",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("capture_id", sa.String(32), nullable=False, index=True),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("delta", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("previous_values", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["capture_id"],
            ["shared.captures.id"],
            ondelete="CASCADE",
        ),
        schema="shared",
    )


def downgrade() -> None:
    op.drop_table("capture_enrichments", schema="shared")
    op.drop_index("ix_captures_group_id", table_name="captures", schema="shared")
    op.drop_column("captures", "group_id", schema="shared")
    op.drop_column("captures", "version", schema="shared")

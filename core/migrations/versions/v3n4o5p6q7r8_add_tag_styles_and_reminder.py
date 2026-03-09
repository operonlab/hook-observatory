"""add tag_styles table and reminder_days column

Revision ID: v3n4o5p6q7r8
Revises: u2m3n4o5p6q7
Create Date: 2026-03-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3n4o5p6q7r8"
down_revision: str | None = "u2m3n4o5p6q7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create finance.tag_styles table
    op.execute("""
        CREATE TABLE IF NOT EXISTS finance.tag_styles (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            styles JSONB NOT NULL DEFAULT '{}',
            created_by TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tag_styles_space
        ON finance.tag_styles(space_id)
    """)

    # Add reminder_days column to finance.subscriptions
    op.add_column(
        "subscriptions",
        sa.Column("reminder_days", sa.Integer(), nullable=True),
        schema="finance",
    )


def downgrade() -> None:
    # Drop reminder_days column from finance.subscriptions
    op.drop_column("subscriptions", "reminder_days", schema="finance")

    # Drop finance.tag_styles table
    op.execute("DROP INDEX IF EXISTS finance.idx_tag_styles_space")
    op.execute("DROP TABLE IF EXISTS finance.tag_styles")

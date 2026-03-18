"""add search_config/topic_type to briefing_topics, cli_command to briefing_analysts

Revision ID: i1j2k3l4m5n6
Revises: a2b3c4d5e6f7, h0i1j2k3l4m5
Create Date: 2026-03-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i1j2k3l4m5n6"
down_revision: str | tuple[str, ...] = ("a2b3c4d5e6f7", "h0i1j2k3l4m5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "briefing_topics",
        sa.Column("search_config", sa.JSON(), server_default=sa.text("'{}'::jsonb"), nullable=True),
        schema="briefing",
    )
    op.add_column(
        "briefing_topics",
        sa.Column("topic_type", sa.String(20), server_default=sa.text("'news'"), nullable=False),
        schema="briefing",
    )
    op.add_column(
        "briefing_analysts",
        sa.Column("cli_command", sa.Text(), nullable=True),
        schema="briefing",
    )


def downgrade() -> None:
    op.drop_column("briefing_analysts", "cli_command", schema="briefing")
    op.drop_column("briefing_topics", "topic_type", schema="briefing")
    op.drop_column("briefing_topics", "search_config", schema="briefing")

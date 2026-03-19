"""drop skill_invocations table — replaced by Anvil station telemetry

Revision ID: m5n6o7p8q9r2
Revises: m5n6o7p8q9r1
Create Date: 2026-03-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "m5n6o7p8q9r2"
down_revision: str | None = "m5n6o7p8q9r1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("skill_invocations", schema="memvault")


def downgrade() -> None:
    op.create_table(
        "skill_invocations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skill_name", sa.String(200), nullable=False),
        sa.Column("source_session", sa.String(64), nullable=False),
        sa.Column("cwd", sa.String(500), nullable=True),
        sa.Column("invoked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(20), server_default=sa.text("'unknown'")),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.UniqueConstraint(
            "space_id",
            "skill_name",
            "source_session",
            "invoked_at",
            name="uq_skill_invocations_space_skill_session_at",
        ),
        schema="memvault",
    )

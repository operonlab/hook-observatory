"""add skill_profiles table for KAS Skill dimension

Revision ID: m5n6o7p8q9r1
Revises: m5n6o7p8q9r0
Create Date: 2026-03-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSON

revision: str = "m5n6o7p8q9r1"
down_revision: str | None = "m5n6o7p8q9r0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_profiles",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("space_id", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skill_name", sa.String(200), nullable=False),
        sa.Column("total_uses", sa.Integer, server_default=sa.text("0")),
        sa.Column("recent_uses", sa.Integer, server_default=sa.text("0")),
        sa.Column("success_rate", sa.Float, server_default=sa.text("0")),
        sa.Column("avg_duration_ms", sa.Float, nullable=True),
        sa.Column("auto_rate", sa.Float, nullable=True),
        sa.Column("common_patterns", ARRAY(sa.Text), nullable=True),
        sa.Column("learned_preferences", JSON, nullable=True),
        sa.Column("pitfalls", JSON, nullable=True),
        sa.Column("proficiency_level", sa.String(20), server_default=sa.text("'novice'")),
        sa.Column("health_score", sa.Float, nullable=True),
        sa.Column("evolution_notes", ARRAY(sa.Text), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("space_id", "skill_name", name="uq_skill_profiles_space_skill"),
        schema="memvault",
    )


def downgrade() -> None:
    op.drop_table("skill_profiles", schema="memvault")

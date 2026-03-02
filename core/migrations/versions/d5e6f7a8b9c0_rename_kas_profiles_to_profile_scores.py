"""rename kas_profiles to profile_scores

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-02-26
"""

from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None

SCHEMA = "memvault"


def upgrade() -> None:
    op.rename_table("kas_profiles", "profile_scores", schema=SCHEMA)
    op.execute(f"ALTER INDEX {SCHEMA}.idx_kas_space RENAME TO idx_profile_scores_space")


def downgrade() -> None:
    op.execute(f"ALTER INDEX {SCHEMA}.idx_profile_scores_space RENAME TO idx_kas_space")
    op.rename_table("profile_scores", "kas_profiles", schema=SCHEMA)

"""KAS Phase G: DROP TABLE attitude_facts + skill_profiles.

資料已於 Phase A 遷移至 blocks(block_type='attitude')。
Phase B~F 已移除所有 ORM / service / route / lint 引用。
此 migration 為最後一步：從 DB 徹底移除 KAS 專用表。

⚠️  僅在 Mac 主機執行 — 遠端機器不可執行此 migration。

Revision ID: mv20260411kg01
Revises: mv20260411ka01
Create Date: 2026-04-11
"""

from alembic import op

revision = "mv20260411kg01"
down_revision = "mv20260411ka01"
branch_labels = None
depends_on = None

SCHEMA = "memvault"


def upgrade() -> None:
    # Drop indexes first (PostgreSQL drops them automatically with the table,
    # but being explicit avoids errors if they were created independently)
    op.drop_table("skill_profiles", schema=SCHEMA)
    op.drop_table("attitude_facts", schema=SCHEMA)


def downgrade() -> None:
    # Downgrade intentionally not implemented — data has been migrated to blocks.
    # Restoring the tables would require a full data rollback from blocks.
    raise NotImplementedError(
        "KAS Phase G downgrade not supported — attitude_facts data lives in blocks."
    )

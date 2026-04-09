"""KAS Phase A: 將 attitude_facts 遷移至 blocks (block_type='attitude').

將所有 current attitude_facts (superseded_by IS NULL AND invalid_at IS NULL) 複製
至 memvault.blocks，使 blocks 成為唯一事實真相 (Single Source of Truth)。

遷移邏輯：
- content  = attitude_facts.fact
- block_type = 'attitude'
- tags    = ARRAY[category]  (category 轉為首個 tag)
- 以 content + space_id 做 dedup，避免重跑時重複插入

Revision ID: mv20260411ka01
Revises: mv20260410af01
Create Date: 2026-04-11
"""

from alembic import op

revision = "mv20260411ka01"
down_revision = "mv20260410af01"
branch_labels = None
depends_on = None

SCHEMA = "memvault"

_MIGRATE_SQL = """
INSERT INTO memvault.blocks (
    id,
    space_id,
    created_by,
    created_at,
    updated_at,
    source_session,
    content,
    block_type,
    tags,
    confidence,
    deleted_at,
    access_count,
    last_accessed_at,
    invalid_at,
    superseded_by,
    invalidation_reason
)
SELECT
    replace(gen_random_uuid()::text, '-', '')  AS id,
    af.space_id,
    af.created_by,
    af.created_at,
    NOW()                                       AS updated_at,
    NULL                                        AS source_session,
    af.fact                                     AS content,
    'attitude'                                  AS block_type,
    ARRAY[af.category]                          AS tags,
    af.confidence,
    NULL                                        AS deleted_at,
    0                                           AS access_count,
    NULL                                        AS last_accessed_at,
    NULL                                        AS invalid_at,
    NULL                                        AS superseded_by,
    NULL                                        AS invalidation_reason
FROM memvault.attitude_facts af
WHERE af.superseded_by IS NULL
  AND af.invalid_at IS NULL
  AND NOT EXISTS (
        SELECT 1
        FROM memvault.blocks b
        WHERE b.content   = af.fact
          AND b.space_id  = af.space_id
          AND b.block_type = 'attitude'
  )
"""

_ROLLBACK_SQL = """
DELETE FROM memvault.blocks
WHERE block_type = 'attitude'
  AND EXISTS (
        SELECT 1
        FROM memvault.attitude_facts af
        WHERE af.fact    = memvault.blocks.content
          AND af.space_id = memvault.blocks.space_id
  )
"""


def upgrade() -> None:
    op.execute(_MIGRATE_SQL)


def downgrade() -> None:
    # 僅刪除由本遷移產生的 attitude blocks（內容能在 attitude_facts 中找到）
    op.execute(_ROLLBACK_SQL)

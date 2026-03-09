"""dailyos multi-active method support with dimension-based conflict detection

Revision ID: c9d0e1f2g3h4
Revises: b8c9d0e1f2g3
Create Date: 2026-03-08
"""

import json

from alembic import op

revision = "c9d0e1f2g3h4"
down_revision = "b8c9d0e1f2g3"
branch_labels = None
depends_on = None

# Dimension assignments per preset slug
DIMENSIONS = {
    "ivy-lee": ["prioritization"],
    "one-three-five": ["prioritization"],
    "eat-the-frog": ["prioritization"],
    "eisenhower": ["prioritization"],
    "time-blocking": ["execution"],
    "pomodoro": ["execution"],
    "kanban-daily": ["flow"],
    "daily-reset": ["ritual"],
}


def upgrade() -> None:
    # 1. Drop old single-active unique index
    op.execute("DROP INDEX IF EXISTS dailyos.idx_ms_unique_active")

    # 2. Create new multi-active unique index (same method can't be activated twice)
    op.execute(
        "CREATE UNIQUE INDEX idx_ms_unique_active_method "
        "ON dailyos.method_selections (space_id, context, method_id) "
        "WHERE deleted_at IS NULL AND is_active = true"
    )

    # 3. Update preset method configs to include dimensions
    for slug, dims in DIMENSIONS.items():
        dims_json = json.dumps(dims)
        op.execute(
            f"UPDATE dailyos.methods "
            f"SET config = jsonb_set(config, '{{dimensions}}', '{dims_json}'::jsonb) "
            f"WHERE slug = '{slug}' AND is_preset = true"
        )


def downgrade() -> None:
    # 1. Drop multi-active index
    op.execute("DROP INDEX IF EXISTS dailyos.idx_ms_unique_active_method")

    # 2. Deactivate all but the most recent active selection per space+context
    op.execute(
        "UPDATE dailyos.method_selections SET is_active = false, "
        "deactivated_at = NOW() "
        "WHERE id NOT IN ("
        "  SELECT DISTINCT ON (space_id, context) id "
        "  FROM dailyos.method_selections "
        "  WHERE is_active = true AND deleted_at IS NULL "
        "  ORDER BY space_id, context, activated_at DESC"
        ")"
    )

    # 3. Recreate old single-active unique index
    op.execute(
        "CREATE UNIQUE INDEX idx_ms_unique_active "
        "ON dailyos.method_selections (space_id, context) "
        "WHERE deleted_at IS NULL AND is_active = true"
    )

    # 4. Remove dimensions from preset configs
    for slug in DIMENSIONS:
        op.execute(
            f"UPDATE dailyos.methods "
            f"SET config = config - 'dimensions' "
            f"WHERE slug = '{slug}' AND is_preset = true"
        )

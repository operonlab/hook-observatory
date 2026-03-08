"""seed dailyos preset methods

Revision ID: z7r8s9t0u1v2
Revises: y6q7r8s9t0u1
Create Date: 2026-03-08
"""

import json

from alembic import op
from uuid_utils import uuid7

revision = "z7r8s9t0u1v2"
down_revision = "y6q7r8s9t0u1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
    from modules.dailyos.presets import PRESETS

    for preset in PRESETS:
        preset_id = uuid7().hex
        name_zh = preset.get("name_zh", "").replace("'", "''")
        description = preset.get("description", "").replace("'", "''")
        icon = preset.get("icon", "")
        color = preset.get("color", "")
        layout_type = preset.get("layout_type", "list")
        tags = preset.get("tags", [])
        tags_sql = "ARRAY[" + ",".join(f"'{t}'" for t in tags) + "]::text[]" if tags else "NULL"
        config_json = json.dumps(preset["config"]).replace("'", "''")

        op.execute(
            f"INSERT INTO dailyos.methods "  # noqa: S608
            f"(id, space_id, slug, name, name_zh, description, icon, color, "
            f"is_preset, config, layout_type, tags) VALUES ("
            f"'{preset_id}', 'system', '{preset['slug']}', "
            f"'{preset['name'].replace(chr(39), chr(39)*2)}', "
            f"'{name_zh}', '{description}', '{icon}', '{color}', "
            f"true, '{config_json}'::jsonb, '{layout_type}', {tags_sql})"
        )


def downgrade() -> None:
    op.execute("DELETE FROM dailyos.methods WHERE is_preset = true AND space_id = 'system'")

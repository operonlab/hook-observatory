"""add dailyos method descriptions and daily reset preset

Revision ID: b8c9d0e1f2g3
Revises: z7r8s9t0u1v2
Create Date: 2026-03-08
"""

import json

from alembic import op
from uuid_utils import uuid7

revision = "b8c9d0e1f2g3"
down_revision = "z7r8s9t0u1v2"
branch_labels = None
depends_on = None

DESCRIPTIONS = {
    "ivy-lee": "每晚選出明天最重要的 6 件事，按優先順序排列。隔天從第一件做起，做完才做下一件。未完成的滾入隔天重新排序。百年經典，以簡馭繁。",
    "one-three-five": "每天規劃 1 件大事、3 件中事、5 件小事，共 9 件。大事需要深度專注，中事半小時內可完成，小事是五分鐘雜務。結構化但保持彈性。",
    "eat-the-frog": "一早就做你最抗拒但最重要的那件事。「青蛙」吃完，剩下的一天都會很順。適合拖延症者——把最難的事先解決，心理壓力立刻減半。",
    "time-blocking": "把一天切成時間區塊，每個區塊分配給特定任務。強制單工、防止無意識切換。適合會議多、容易被打斷的人。",
    "eisenhower": "所有待辦按「緊急 × 重要」分入四象限：立刻做、安排時間、委派他人、直接刪除。幫你分辨「看起來急但不重要」的偽優先事項。",
    "kanban-daily": "三欄看板：待辦 → 進行中 → 完成。限制「進行中」不超過 3 件，強制做完一件再開下一件。視覺化進度，減少多工。",
    "pomodoro": "25 分鐘專注 + 5 分鐘休息為一個番茄鐘，每 4 輪長休 15 分鐘。估算任務需幾顆番茄，追蹤實際消耗，持續校準時間感。",
}


def upgrade() -> None:
    # Update descriptions for existing 7 presets
    for slug, desc in DESCRIPTIONS.items():
        escaped = desc.replace("'", "''")
        op.execute(
            f"UPDATE dailyos.methods SET description = '{escaped}' "
            f"WHERE slug = '{slug}' AND is_preset = true"
        )

    # Insert 8th preset: Daily Reset
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
    from modules.dailyos.presets import PRESETS

    preset = next(p for p in PRESETS if p["slug"] == "daily-reset")
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
        f"'{preset['name']}', '{name_zh}', '{description}', "
        f"'{icon}', '{color}', true, '{config_json}'::jsonb, "
        f"'{layout_type}', {tags_sql})"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM dailyos.methods WHERE slug = 'daily-reset' "
        "AND is_preset = true AND space_id = 'system'"
    )
    for slug in DESCRIPTIONS:
        op.execute(
            f"UPDATE dailyos.methods SET description = '' "
            f"WHERE slug = '{slug}' AND is_preset = true"
        )

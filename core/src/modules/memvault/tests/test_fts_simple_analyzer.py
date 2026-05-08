"""Test FTS analyzer migration (english → simple, 2026-05-08).

Reason: 'english' analyzer 對中文不分詞，中文化後 BM25 channel 會歸零。
'simple' 純 unicode tokenize + lowercase，中英混排都能切詞。

驗證點：
1. services.py 用 'simple' 而非 'english'
2. alembic n7o8p9q0r1s2 migration 重建了 idx_blocks_fts
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]


def test_services_uses_simple_analyzer():
    """services.py FTS 應用 'simple' analyzer，不該再硬編 'english'."""
    p = REPO_ROOT / "core" / "src" / "modules" / "memvault" / "services.py"
    content = p.read_text(encoding="utf-8")

    # plainto_tsquery / to_tsvector 不該再有 'english' literal（註解可有說明）
    code_only = "\n".join(
        line for line in content.splitlines()
        if "plainto_tsquery" in line or "to_tsvector" in line
    )
    # 排除註解行
    code_only_no_comment = "\n".join(
        line for line in code_only.splitlines()
        if not line.lstrip().startswith("#")
    )
    assert '"english"' not in code_only_no_comment, \
        f"services.py FTS still uses 'english' analyzer:\n{code_only_no_comment}"
    assert '"simple"' in code_only_no_comment, \
        f"services.py FTS missing 'simple' analyzer:\n{code_only_no_comment}"


def test_migration_rebuilds_idx_blocks_fts():
    """alembic n7o8p9q0r1s2 migration 應 drop + recreate idx_blocks_fts with 'simple'."""
    p = REPO_ROOT / "core" / "migrations" / "versions" / "n7o8p9q0r1s2_kg_triple_envelope_full.py"
    assert p.exists(), f"Migration n7o8p9q0r1s2 not found at {p}"

    content = p.read_text(encoding="utf-8")
    # upgrade() 應 drop 舊 + create 新（with 'simple'）
    assert "DROP INDEX" in content and "idx_blocks_fts" in content
    assert "to_tsvector('simple', content)" in content
    # downgrade() 應反向（'simple' → 'english'）
    assert "to_tsvector('english', content)" in content


@pytest.mark.skipif(True, reason="DB integration test — run manually after `alembic upgrade head`")
def test_db_idx_blocks_fts_uses_simple():
    """[manual] 跑完 alembic upgrade 後驗 DB 端 GIN index 用 'simple' analyzer.

    Run:
        pytest -k test_db_idx_blocks_fts_uses_simple --no-skip
    """
    import asyncio

    import asyncpg

    async def _check():
        c = await asyncpg.connect("postgresql://joneshong:dev_12345@localhost/workshop")
        row = await c.fetchrow("""
            SELECT indexdef FROM pg_indexes
            WHERE schemaname='memvault' AND indexname='idx_blocks_fts'
        """)
        await c.close()
        return row

    row = asyncio.run(_check())
    assert row is not None, "idx_blocks_fts not found"
    assert "simple" in row["indexdef"]
    assert "english" not in row["indexdef"]

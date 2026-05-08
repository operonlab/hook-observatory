"""Test display_zh column has been fully removed (2026-05-08 中文化重構).

display_zh 反譯欄位廢除，subject/object 直存中文 surface form。
驗證所有應移除的位置都已清空。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

# Repo root: 三層 .. 從 tests/ → memvault/ → modules/ → src/ → core/
REPO_ROOT = Path(__file__).resolve().parents[5]


def test_orm_no_display_zh():
    """Triple ORM 不該有 display_zh column."""
    from src.modules.memvault.kg_models import Triple

    columns = {c.name for c in Triple.__table__.columns}
    assert "display_zh" not in columns


def test_pydantic_no_display_zh():
    """TripleResponse / TripleCreate 不該有 display_zh field."""
    from src.modules.memvault.kg_schemas import TripleCreate, TripleResponse

    assert "display_zh" not in TripleCreate.model_fields
    assert "display_zh" not in TripleResponse.model_fields


def test_translate_kg_zh_script_deleted():
    """translate_kg_zh.py 應已刪除（display_zh 砍掉後失去用途）."""
    p = REPO_ROOT / "core" / "src" / "modules" / "memvault" / "scripts" / "translate_kg_zh.py"
    assert not p.exists(), f"translate_kg_zh.py should be deleted, but exists at {p}"


def test_kg_services_no_display_zh_reference():
    """kg_services.py 不該有 display_zh 引用（除註解中提到的「廢除」說明）."""
    p = REPO_ROOT / "core" / "src" / "modules" / "memvault" / "kg_services.py"
    content = p.read_text(encoding="utf-8")
    # 只查 code-level 引用，註解可保留
    code_lines = [
        line for line in content.splitlines()
        if "display_zh" in line and not line.strip().startswith("#")
    ]
    assert not code_lines, f"kg_services.py still has code-level display_zh: {code_lines}"


def test_frontend_types_no_display_zh():
    """workbench types/index.ts Triple interface 不該有 display_zh."""
    p = REPO_ROOT / "workbench" / "src" / "modules" / "memvault" / "types" / "index.ts"
    content = p.read_text(encoding="utf-8")
    assert "display_zh" not in content, "Frontend types/index.ts still has display_zh"


def test_frontend_components_no_display_zh():
    """workbench KgExplorerPanel.tsx / TriplesPage.tsx 不該還在渲染 display_zh."""
    panels = [
        REPO_ROOT / "workbench" / "src" / "modules" / "memvault" / "components" / "KgExplorerPanel.tsx",
        REPO_ROOT / "workbench" / "src" / "modules" / "memvault" / "components" / "knowledge" / "TriplesPage.tsx",
    ]
    for p in panels:
        content = p.read_text(encoding="utf-8")
        assert "display_zh" not in content, f"{p.name} still references display_zh"

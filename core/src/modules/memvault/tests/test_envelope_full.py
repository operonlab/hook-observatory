"""Test Triple envelope schema (2026-05-08 中文化重構).

驗 9 個 envelope 欄位 + extra_metadata 都正確定義在 ORM 與 Pydantic schema。
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pydantic")

ENVELOPE_FIELDS = [
    "kind",
    "modality",
    "polarity",
    "raw_quote",
    "temporal",
    "attribution",
    "speaker_id",
    "refs_triple_id",
    "confidence",
    "extra_metadata",
]


def test_orm_has_envelope_columns():
    """Triple ORM 必須有 9 envelope cols + extra_metadata."""
    from src.modules.memvault.kg_models import Triple

    columns = {c.name for c in Triple.__table__.columns}
    for field in ENVELOPE_FIELDS:
        assert field in columns, f"Triple ORM missing envelope column: {field}"


def test_orm_no_display_zh():
    """display_zh 應已 drop，舊欄位不該出現."""
    from src.modules.memvault.kg_models import Triple

    columns = {c.name for c in Triple.__table__.columns}
    assert "display_zh" not in columns, "display_zh should be dropped"


def test_pydantic_create_has_envelope():
    """TripleCreate schema 必須有 envelope fields + tags + signal_type."""
    from src.modules.memvault.kg_schemas import TripleCreate

    fields = TripleCreate.model_fields
    for field in ENVELOPE_FIELDS:
        assert field in fields, f"TripleCreate missing field: {field}"
    assert "tags" in fields
    assert "signal_type" in fields


def test_pydantic_response_has_envelope():
    """TripleResponse schema 必須有 envelope fields，且不含 display_zh."""
    from src.modules.memvault.kg_schemas import TripleResponse

    fields = TripleResponse.model_fields
    for field in ENVELOPE_FIELDS:
        assert field in fields, f"TripleResponse missing field: {field}"
    assert "display_zh" not in fields, "TripleResponse should not have display_zh"


def test_pydantic_create_with_envelope_payload():
    """模擬 LLM 抽取輸出，TripleCreate 應能解析 9 欄 envelope."""
    from src.modules.memvault.kg_schemas import TripleCreate

    payload = {
        "s": "memvault triple 萃取",
        "p": "should",
        "o": "保留中文 surface form",
        "kind": "commitment",
        "modality": "planned",
        "polarity": "positive",
        "raw_quote": "中間層應保留中文 surface form",
        "temporal": {"relative": "之後"},
        "attribution": {"lesson": "純 SVO 失去情境"},
        "speaker": "self",
        "refs": "T1",
        "confidence": 0.85,
        "tags": ["memvault", "中文化", "schema"],
        "signal_type": "decision",
    }
    obj = TripleCreate(**payload)
    assert obj.subject == "memvault triple 萃取"
    assert obj.predicate == "should"
    assert obj.kind == "commitment"
    assert obj.modality == "planned"
    assert obj.polarity == "positive"
    assert obj.raw_quote == "中間層應保留中文 surface form"
    assert obj.temporal == {"relative": "之後"}
    assert obj.attribution == {"lesson": "純 SVO 失去情境"}
    assert obj.speaker_id == "self"  # AliasChoices: speaker → speaker_id
    assert obj.refs_triple_id == "T1"  # AliasChoices: refs → refs_triple_id
    assert obj.confidence == 0.85
    assert obj.tags == ["memvault", "中文化", "schema"]
    assert obj.signal_type == "decision"


def test_pydantic_create_envelope_optional():
    """envelope 大部分欄位 nullable，最小 SPO triple 仍可建立."""
    from src.modules.memvault.kg_schemas import TripleCreate

    obj = TripleCreate(s="A", p="uses", o="B")
    assert obj.kind == "event"  # default
    assert obj.modality is None
    assert obj.raw_quote is None
    assert obj.temporal is None
    assert obj.confidence is None


def test_modality_uses_epistemic_values():
    """modality 應接受 epistemic 6 值 (observed/planned/desired/hypothesized/regretted/retracted)，
    這是個人記憶情態（非 deontic）。schema 上是 free string 不強制 enum，
    這個測試僅做文件化記錄"""
    from src.modules.memvault.kg_schemas import TripleCreate

    epistemic_values = ["observed", "planned", "desired", "hypothesized", "regretted", "retracted"]
    for m in epistemic_values:
        obj = TripleCreate(s="X", p="uses", o="Y", modality=m)
        assert obj.modality == m

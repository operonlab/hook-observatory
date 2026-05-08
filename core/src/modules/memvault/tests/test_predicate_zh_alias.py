"""Test predicate ZH alias normalization (2026-05-08 中文化重構).

預期：normalize_predicate("使用") → "uses" 等 30+ 對應。
Reason: 既有 LLM 抽到中文動詞無路可選，被迫翻譯成英文。加 alias 表後
        中文 predicate（譬如 "依賴"、"造成"）能被歸一化到英文 canonical。
"""

from __future__ import annotations

import pytest

pytest.importorskip("kg_ops")

from kg_ops.predicates import VALID_PREDICATES, normalize_predicate


# (alias, expected canonical) 對照表 — 涵蓋 8 個 category 各至少 1 例
ZH_ALIAS_CASES = [
    # Dependency
    ("使用", "uses"),
    ("用", "uses"),
    ("採用", "uses"),
    ("需要", "requires"),
    ("依賴", "depends_on"),
    # Configuration
    ("搭配", "configured_with"),
    ("格式是", "format_is"),
    ("預設是", "default_is"),
    # Causality
    ("造成", "causes"),
    ("導致", "causes"),
    ("防止", "prevents"),
    ("修復", "fixes"),
    ("解決", "fixes"),
    ("啟用", "enables"),
    # Prescriptive
    ("應該", "should"),
    ("建議", "should"),
    ("不應該", "should_NOT"),
    ("禁止", "should_NOT"),
    # Pattern
    ("模式是", "pattern_is"),
    ("流程是", "flow_is"),
    ("實作為", "implemented_as"),
    # Decision
    ("選用", "chosen_over"),
    ("原因是", "reason_for"),
    ("因為", "reason_for"),
    # Effect
    ("提升", "improves"),
    ("改善", "improves"),
    ("降低", "degrades"),
    ("削弱", "degrades"),
    # Mapping
    ("對應到", "maps_to"),
    ("等於", "maps_to"),
]


@pytest.mark.parametrize("alias,expected", ZH_ALIAS_CASES)
def test_zh_alias_to_canonical(alias: str, expected: str):
    """每個中文 alias 必須能歸一化到正確英文 canonical."""
    canonical = normalize_predicate(alias)
    assert canonical == expected, f"normalize_predicate('{alias}') = '{canonical}', expected '{expected}'"
    assert expected in VALID_PREDICATES, f"canonical '{expected}' not in VALID_PREDICATES"


def test_predicates_contain_18_canonical():
    """確保 18 canonical predicate 都還在."""
    expected_18 = {
        "uses", "requires", "depends_on",
        "configured_with", "format_is", "default_is",
        "causes", "prevents", "fixes", "enables",
        "should", "should_NOT",
        "pattern_is", "flow_is", "implemented_as",
        "chosen_over", "reason_for",
        "improves", "degrades",
        "maps_to",
    }
    # 注意：實際是 20（PREDICATE_VOCABULARY 註解寫的是 18-20，看實際）
    assert expected_18.issubset(VALID_PREDICATES), \
        f"Missing canonical: {expected_18 - VALID_PREDICATES}"


def test_zh_alias_count_at_least_30():
    """確保中文 alias 表加了至少 30 條（不退化）."""
    from kg_ops.predicates import PREDICATE_ALIASES
    cjk_aliases = [k for k in PREDICATE_ALIASES.keys() if any('一' <= ch <= '鿿' for ch in k)]
    assert len(cjk_aliases) >= 30, f"Only {len(cjk_aliases)} CJK aliases, expected ≥ 30"


def test_english_aliases_still_work():
    """既有英文 alias 不能被新中文 alias 破壞."""
    assert normalize_predicate("depends on") == "depends_on"
    assert normalize_predicate("must") == "should"
    assert normalize_predicate("triggers") == "causes"

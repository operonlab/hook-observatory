"""Adversarial structural tests for KAS separation Phase E (lint.py) and Phase F (kg_models / kg_schemas).

六鐵律遵守聲明
──────────────
1. Mutation thinking  — 每個測試標記了目標 mutation（若有人把刪除的程式復原，測試應失敗）
2. 寫測分離          — 本檔是 adversary，只驗「清除是否完整」，不負責功能邏輯
3. 不變量優先        — 測「KAS 已消失 / KG 仍健在」兩類不變量
4. Runtime 回歸      — 確認刪除不影響倖存的 import + callable 性
5. Mock 邊界         — 純 import/inspect，不需要 DB/Qdrant/Mock
6. 草稿不是成品      — 額外掃原始碼字串，找殘留 KAS 符號
"""

from __future__ import annotations

import inspect
import os
import sys

import pytest

# ── 路徑設定（worktree 隔離，不依賴安裝）─────────────────────────────────────
_CORE = os.path.join(os.path.dirname(__file__), "..", "..")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from src.modules.memvault import kg_models, kg_schemas, lint

# ════════════════════════════════════════════════════════════════════════════
# Phase E — lint.py KAS 函式刪除確認
# ════════════════════════════════════════════════════════════════════════════


class TestPhaseEKASFunctionsRemoved:
    """INV-1 ~ INV-6: KAS lint 函式必須完全不存在於 lint 模組。

    Mutation target: 若有人把以下任一函式 restore 回 lint.py，對應測試即失敗。
    """

    def test_inv1_check_attitude_chain_integrity_removed(self):
        """INV-1 — AttitudeFact 版本連結函式應已刪除。"""
        assert not hasattr(lint, "check_attitude_chain_integrity"), (
            "MUTATION DETECTED: check_attitude_chain_integrity 已被復原，KAS 清除不完整"
        )

    def test_inv2_check_attitude_dedup_removed(self):
        """INV-2 — 重複 attitude 偵測函式應已刪除。"""
        assert not hasattr(lint, "check_attitude_dedup"), (
            "MUTATION DETECTED: check_attitude_dedup 已被復原，KAS 清除不完整"
        )

    def test_inv3_check_attitude_semantic_contradictions_removed(self):
        """INV-3 — 語義矛盾（LLM based）attitude 函式應已刪除。"""
        assert not hasattr(lint, "check_attitude_semantic_contradictions"), (
            "MUTATION DETECTED: check_attitude_semantic_contradictions 已被復原，KAS 清除不完整"
        )

    def test_inv4_check_attitude_temporal_staleness_removed(self):
        """INV-4 — 時間過期 attitude 函式應已刪除。"""
        assert not hasattr(lint, "check_attitude_temporal_staleness"), (
            "MUTATION DETECTED: check_attitude_temporal_staleness 已被復原，KAS 清除不完整"
        )

    def test_inv5_check_skill_profile_drift_removed(self):
        """INV-5 — SkillProfile 同步檢查函式應已刪除。"""
        assert not hasattr(lint, "check_skill_profile_drift"), (
            "MUTATION DETECTED: check_skill_profile_drift 已被復原，KAS 清除不完整"
        )

    def test_inv6_remediate_attitude_conflicts_removed(self):
        """INV-6 — 自動修復 attitude 衝突函式應已刪除。"""
        assert not hasattr(lint, "remediate_attitude_conflicts"), (
            "MUTATION DETECTED: remediate_attitude_conflicts 已被復原，KAS 清除不完整"
        )


class TestPhaseEKGFunctionsSurvive:
    """INV-7 ~ INV-11: 非 KAS 的 KG lint 函式必須保留且可呼叫（regression 防護）。

    Mutation target: 若有人在清理過程中意外刪除這些函式，測試失敗。
    """

    def test_inv7_check_contradictions_survives(self):
        """INV-7 — 三元組語義矛盾函式應保留且可呼叫。"""
        assert hasattr(lint, "check_contradictions"), "check_contradictions 意外消失"
        assert callable(lint.check_contradictions), "check_contradictions 不可呼叫"

    def test_inv8_check_stale_triples_survives(self):
        """INV-8 — 過期三元組函式應保留且可呼叫。"""
        assert hasattr(lint, "check_stale_triples"), "check_stale_triples 意外消失"
        assert callable(lint.check_stale_triples), "check_stale_triples 不可呼叫"

    def test_inv9_check_orphan_entities_survives(self):
        """INV-9 — 孤立實體函式應保留且可呼叫。"""
        assert hasattr(lint, "check_orphan_entities"), "check_orphan_entities 意外消失"
        assert callable(lint.check_orphan_entities), "check_orphan_entities 不可呼叫"

    def test_inv10_check_knowledge_conflicts_survives(self):
        """INV-10 — 知識衝突管道函式應保留且可呼叫。"""
        assert hasattr(lint, "check_knowledge_conflicts"), "check_knowledge_conflicts 意外消失"
        assert callable(lint.check_knowledge_conflicts), "check_knowledge_conflicts 不可呼叫"

    def test_inv11_check_grounding_survives(self):
        """INV-11 — grounding 驗證函式應保留且可呼叫。"""
        assert hasattr(lint, "check_grounding"), "check_grounding 意外消失"
        assert callable(lint.check_grounding), "check_grounding 不可呼叫"

    def test_check_dangling_refs_survives(self):
        """Extra regression — 懸空引用函式應保留且可呼叫。"""
        assert hasattr(lint, "check_dangling_refs"), "check_dangling_refs 意外消失"
        assert callable(lint.check_dangling_refs), "check_dangling_refs 不可呼叫"


# ════════════════════════════════════════════════════════════════════════════
# Phase F — kg_models.py KAS ORM 類別刪除確認
# ════════════════════════════════════════════════════════════════════════════


class TestPhaseFKGModelsKASRemoved:
    """INV-12 ~ INV-13: KAS ORM 類別不得存在。

    Mutation target: 若有人把 AttitudeFact / SkillProfile 模型 restore，測試失敗。
    """

    def test_inv12_attitude_fact_model_removed(self):
        """INV-12 — AttitudeFact ORM 類別應已刪除。"""
        assert not hasattr(kg_models, "AttitudeFact"), (
            "MUTATION DETECTED: AttitudeFact 已被復原至 kg_models，KAS 清除不完整"
        )

    def test_inv13_skill_profile_model_removed(self):
        """INV-13 — SkillProfile ORM 類別應已刪除。"""
        assert not hasattr(kg_models, "SkillProfile"), (
            "MUTATION DETECTED: SkillProfile 已被復原至 kg_models，KAS 清除不完整"
        )


class TestPhaseFKGModelsSurvive:
    """INV-14 ~ INV-17: 保留的 KG ORM 類別必須正常 import（regression 防護）。

    Mutation target: 若清理誤刪這些類別，測試失敗。
    """

    def test_inv14_triple_model_survives(self):
        """INV-14 — Triple ORM 類別應保留。"""
        assert hasattr(kg_models, "Triple"), "Triple ORM 類別意外消失"
        assert inspect.isclass(kg_models.Triple), "Triple 不是 class"

    def test_inv15_entity_canonical_survives(self):
        """INV-15 — EntityCanonical ORM 類別應保留。"""
        assert hasattr(kg_models, "EntityCanonical"), "EntityCanonical ORM 類別意外消失"
        assert inspect.isclass(kg_models.EntityCanonical), "EntityCanonical 不是 class"

    def test_inv16_community_survives(self):
        """INV-16 — Community ORM 類別應保留。"""
        assert hasattr(kg_models, "Community"), "Community ORM 類別意外消失"
        assert inspect.isclass(kg_models.Community), "Community 不是 class"

    def test_inv17_community_summary_survives(self):
        """INV-17 — CommunitySummary ORM 類別應保留。"""
        assert hasattr(kg_models, "CommunitySummary"), "CommunitySummary ORM 類別意外消失"
        assert inspect.isclass(kg_models.CommunitySummary), "CommunitySummary 不是 class"


# ════════════════════════════════════════════════════════════════════════════
# Phase F — kg_schemas.py KAS Pydantic 類別刪除確認
# ════════════════════════════════════════════════════════════════════════════


class TestPhaseFKGSchemasKASRemoved:
    """INV-18 ~ INV-22: KAS schema 類別不得存在。

    Mutation target: 若有人把任何 KAS schema 復原，對應測試失敗。
    """

    def test_inv18_attitude_fact_create_removed(self):
        """INV-18 — AttitudeFactCreate 應已刪除。"""
        assert not hasattr(kg_schemas, "AttitudeFactCreate"), (
            "MUTATION DETECTED: AttitudeFactCreate 已被復原至 kg_schemas"
        )

    def test_inv19_attitude_fact_response_removed(self):
        """INV-19 — AttitudeFactResponse 應已刪除。"""
        assert not hasattr(kg_schemas, "AttitudeFactResponse"), (
            "MUTATION DETECTED: AttitudeFactResponse 已被復原至 kg_schemas"
        )

    def test_inv19b_attitude_fact_update_removed(self):
        """INV-19b — AttitudeFactUpdate 應已刪除。"""
        assert not hasattr(kg_schemas, "AttitudeFactUpdate"), (
            "MUTATION DETECTED: AttitudeFactUpdate 已被復原至 kg_schemas"
        )

    def test_inv20_attitude_evolve_request_removed(self):
        """INV-20 — AttitudeEvolveRequest 應已刪除。"""
        assert not hasattr(kg_schemas, "AttitudeEvolveRequest"), (
            "MUTATION DETECTED: AttitudeEvolveRequest 已被復原至 kg_schemas"
        )

    def test_inv20b_attitude_evolve_result_removed(self):
        """INV-20b — AttitudeEvolveResult 應已刪除。"""
        assert not hasattr(kg_schemas, "AttitudeEvolveResult"), (
            "MUTATION DETECTED: AttitudeEvolveResult 已被復原至 kg_schemas"
        )

    def test_inv21_skill_profile_response_removed(self):
        """INV-21 — SkillProfileResponse 應已刪除。"""
        assert not hasattr(kg_schemas, "SkillProfileResponse"), (
            "MUTATION DETECTED: SkillProfileResponse 已被復原至 kg_schemas"
        )

    def test_inv22_skill_profile_upsert_removed(self):
        """INV-22 — SkillProfileUpsert 應已刪除。"""
        assert not hasattr(kg_schemas, "SkillProfileUpsert"), (
            "MUTATION DETECTED: SkillProfileUpsert 已被復原至 kg_schemas"
        )


class TestPhaseFKGSchemasSurvive:
    """INV-23 ~ INV-24: 保留的 KG schema 類別必須正常 import（regression 防護）。"""

    def test_inv23_triple_create_survives(self):
        """INV-23 — TripleCreate schema 應保留。"""
        assert hasattr(kg_schemas, "TripleCreate"), "TripleCreate schema 意外消失"
        assert inspect.isclass(kg_schemas.TripleCreate), "TripleCreate 不是 class"

    def test_triple_batch_create_survives(self):
        """Extra regression — TripleBatchCreate schema 應保留。"""
        assert hasattr(kg_schemas, "TripleBatchCreate"), "TripleBatchCreate schema 意外消失"
        assert inspect.isclass(kg_schemas.TripleBatchCreate), "TripleBatchCreate 不是 class"

    def test_triple_response_survives(self):
        """Extra regression — TripleResponse schema 應保留。"""
        assert hasattr(kg_schemas, "TripleResponse"), "TripleResponse schema 意外消失"
        assert inspect.isclass(kg_schemas.TripleResponse), "TripleResponse 不是 class"

    def test_community_response_survives(self):
        """Extra regression — CommunityResponse schema 應保留。"""
        assert hasattr(kg_schemas, "CommunityResponse"), "CommunityResponse schema 意外消失"
        assert inspect.isclass(kg_schemas.CommunityResponse), "CommunityResponse 不是 class"

    def test_inv24_lint_finding_response_survives(self):
        """INV-24 — LintFindingResponse schema 應保留。"""
        assert hasattr(kg_schemas, "LintFindingResponse"), "LintFindingResponse schema 意外消失"
        assert inspect.isclass(kg_schemas.LintFindingResponse), "LintFindingResponse 不是 class"

    def test_lint_report_response_survives(self):
        """Extra regression — LintReportResponse schema 應保留。"""
        assert hasattr(kg_schemas, "LintReportResponse"), "LintReportResponse schema 意外消失"
        assert inspect.isclass(kg_schemas.LintReportResponse), "LintReportResponse 不是 class"


# ════════════════════════════════════════════════════════════════════════════
# Phase E+F — 原始碼字串掃描（Adversarial INV-25 ~ INV-27）
# ════════════════════════════════════════════════════════════════════════════


def _read_source(module) -> str:
    """取得模組原始碼，inspect 找不到就讀 __file__。"""
    try:
        return inspect.getsource(module)
    except (OSError, TypeError):
        src_file = getattr(module, "__file__", None)
        if src_file and os.path.isfile(src_file):
            with open(src_file, encoding="utf-8") as f:
                return f.read()
        raise


class TestAdversarialSourceScan:
    """INV-25 ~ INV-27: 原始碼層級掃描，防止 KAS 符號以任何形式殘留。

    Mutation target: 若有人留下 commented-out 或 partial 的 KAS 程式，此處捕捉。
    注意：只掃「有語義的殘留」，不掃 docstring/comment 中的名稱解釋。
    """

    def test_inv25_lint_source_no_attitude_facts_table_query(self):
        """INV-25 — lint.py 原始碼不應包含 'attitude_facts' 作為查詢目標（table name）。

        允許出現在 docstring 或 comment 中，但不允許出現在 SQL/ORM 查詢字串裡。
        策略：掃整份原始碼不含 'attitude_facts' 字串（包含 quoted）。
        """
        source = _read_source(lint)
        assert "attitude_facts" not in source, (
            "INV-25 VIOLATED: lint.py 原始碼中仍含有 'attitude_facts'，"
            "KAS 查詢可能未完全清除"
        )

    def test_inv26_kg_models_source_no_attitude_facts_tablename(self):
        """INV-26 — kg_models.py 原始碼中不應含有 'attitude_facts' 作為 __tablename__。"""
        source = _read_source(kg_models)
        assert "attitude_facts" not in source, (
            "INV-26 VIOLATED: kg_models.py 仍含 'attitude_facts'，"
            "AttitudeFact ORM 可能未完全刪除"
        )

    def test_inv27_kg_schemas_source_no_attitude_fact_symbol(self):
        """INV-27 — kg_schemas.py 原始碼中不應含有 'AttitudeFact' 字串。"""
        source = _read_source(kg_schemas)
        assert "AttitudeFact" not in source, (
            "INV-27 VIOLATED: kg_schemas.py 仍含 'AttitudeFact'，"
            "KAS schema 可能未完全刪除"
        )

    def test_kg_schemas_source_no_skill_profile_symbol(self):
        """Extra adversarial — kg_schemas.py 原始碼中不應含有 'SkillProfile' 字串。"""
        source = _read_source(kg_schemas)
        assert "SkillProfile" not in source, (
            "kg_schemas.py 仍含 'SkillProfile'，KAS schema 可能未完全刪除"
        )

    def test_kg_models_source_no_skill_profiles_tablename(self):
        """Extra adversarial — kg_models.py 原始碼中不應含有 'skill_profiles' 字串。"""
        source = _read_source(kg_models)
        assert "skill_profiles" not in source, (
            "kg_models.py 仍含 'skill_profiles'，SkillProfile ORM 可能未完全刪除"
        )

    def test_lint_source_no_attitude_kas_function_names(self):
        """Extra adversarial — lint.py 不應含有任何 KAS 函式名稱字串（即使 commented）。

        掃描六個應刪除的函式名稱。
        """
        source = _read_source(lint)
        kas_function_names = [
            "check_attitude_chain_integrity",
            "check_attitude_dedup",
            "check_attitude_semantic_contradictions",
            "check_attitude_temporal_staleness",
            "check_skill_profile_drift",
            "remediate_attitude_conflicts",
        ]
        found = [name for name in kas_function_names if name in source]
        assert not found, (
            f"INV-EXTRA VIOLATED: lint.py 原始碼中仍殘留 KAS 函式名稱: {found}"
        )

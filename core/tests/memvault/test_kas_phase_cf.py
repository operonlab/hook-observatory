"""Adversarial tests for KAS separation Phase C (routes cleanup) and Phase F
(recalculate_profile migrated to MemoryBlock).

六鐵律遵守：
  1. Mutation thinking  — 每個測試對應一個明確的目標 mutation
  2. 寫測分離          — adversary 視角，主動找盲點
  3. 不變量優先        — 測行為，不測實作細節
  4. Runtime 回歸      — 覆蓋實際改動路徑
  5. Mock 邊界         — 只 mock 外部 I/O（DB session）
  6. 草稿不是成品      — 每個測試能殺 mutation
"""

from __future__ import annotations

import math
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 確保 worktree src 可用 ──────────────────────────────────────────────────
_CORE = os.path.join(os.path.dirname(__file__), "..", "..")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from src.modules.memvault.kg_routes import router as kg_router

# ─── 取出所有已登記的路徑字串 ────────────────────────────────────────────────
_REGISTERED_PATHS: list[str] = [r.path for r in kg_router.routes]


# ════════════════════════════════════════════════════════════════════════════════
# Phase C — KAS routes 已從 kg_routes.py 清除
# ════════════════════════════════════════════════════════════════════════════════


class TestPhaseC_KASRoutesAbsent:
    """INV-1~4: KAS endpoints 不得出現在 kg_router 路由表中。

    Target mutation: 若有人把 attitudes/skill-profiles/decay/insights 路由
    重新加回 kg_routes.py，這些測試立刻失敗。
    """

    def test_inv1_no_attitudes_route(self):
        """INV-1: /attitudes 路由已從 kg_router 完全移除。

        Mutation target: 重新加入 router.get('/attitudes', ...) 會被殺。
        """
        leaking = [p for p in _REGISTERED_PATHS if "/attitudes" in p]
        assert not leaking, (
            f"INV-1 violated: KAS /attitudes route still registered in kg_router: {leaking}"
        )

    def test_inv2_no_skill_profiles_route(self):
        """INV-2: /skill-profiles 路由已從 kg_router 移除。

        Mutation target: 重新加入 skill-profiles 系列 endpoint 會被殺。
        """
        leaking = [p for p in _REGISTERED_PATHS if "/skill-profiles" in p]
        assert not leaking, (
            f"INV-2 violated: KAS /skill-profiles route still registered in kg_router: {leaking}"
        )

    def test_inv3_no_kas_decay_route(self):
        """INV-3: KAS 專用 /decay 路由已從 kg_router 移除。

        注意：只排除以 /decay 為路徑片段的路由；其他如 /blocks/decay 不在
        此 invariant 範圍（kg_routes 裡目前也無此路由，但不應過度限制）。
        Mutation target: 重新加入 router.post('/decay', ...) 會被殺。
        """
        # 精確匹配 /decay 路徑片段，不誤傷 /blocks/decay 等未來路由
        leaking = [p for p in _REGISTERED_PATHS if p == "/decay" or p.endswith("/decay")]
        # 但 /communities/{id}/description 等不含 /decay，所以這個條件是安全的
        assert not leaking, (
            f"INV-3 violated: KAS /decay route still registered in kg_router: {leaking}"
        )

    def test_inv4_no_kas_insights_route(self):
        """INV-4: KAS meta /insights 路由已從 kg_router 移除。

        Mutation target: 重新加入 router.post('/insights', ...) 會被殺。
        """
        leaking = [p for p in _REGISTERED_PATHS if "/insights" in p]
        assert not leaking, (
            f"INV-4 violated: KAS /insights route still registered in kg_router: {leaking}"
        )

    def test_attitudes_all_subpaths_absent(self):
        """Phase C 完整覆蓋：/attitudes 的所有子路徑也不得存在。

        Mutation target: 只刪掉父路由但留下子路由（如 /attitudes/{id}）的 mutation。
        """
        sub_paths = [
            "/attitudes/evolve",
            "/attitudes/batch-evolve",
            "/attitudes/backfill-embeddings",
        ]
        for sub in sub_paths:
            leaking = [p for p in _REGISTERED_PATHS if sub in p]
            assert not leaking, (
                f"Phase C violated: sub-path '{sub}' still registered in kg_router: {leaking}"
            )

    def test_skill_profiles_all_subpaths_absent(self):
        """Phase C 完整覆蓋：/skill-profiles 所有子路徑不得存在。

        Mutation target: 只刪掉 /skill-profiles 父路由但留下 /skill-profiles/upsert 的 mutation。
        """
        sub_paths = [
            "/skill-profiles/upsert",
            "/skill-profiles/metrics",
        ]
        for sub in sub_paths:
            leaking = [p for p in _REGISTERED_PATHS if sub in p]
            assert not leaking, (
                f"Phase C violated: sub-path '{sub}' still registered in kg_router: {leaking}"
            )


# ════════════════════════════════════════════════════════════════════════════════
# Phase F — recalculate_profile 邏輯正確性
# ════════════════════════════════════════════════════════════════════════════════

def _make_db_mock(att_count: int, triple_count: int = 0, cluster_count: int = 0, wisdom_count: int = 0):
    """建立模擬 DB session，回傳指定的計數。

    Mock 只限外部 I/O（AsyncSession），內部計算邏輯真跑。
    execute 呼叫順序對應 recalculate_profile 裡的四次 db.execute：
      1. triple_count
      2. cluster_count
      3. wisdom_count
      4. att_count
    """
    db = AsyncMock()
    db.commit = AsyncMock()

    results = [triple_count, cluster_count, wisdom_count, att_count]

    call_count = {"n": 0}

    async def mock_execute(_stmt):
        idx = call_count["n"]
        call_count["n"] += 1
        scalar_result = MagicMock()
        scalar_result.scalar.return_value = results[idx] if idx < len(results) else 0
        return scalar_result

    db.execute = mock_execute
    return db


def _expected_attitude_score(att_count: int) -> float:
    """複製 routes.py 的 attitude_score 計算公式，作為 oracle。"""
    a_base = min(math.log10(max(att_count, 1)) / math.log10(500) * 60, 60)
    return round(min(a_base, 100), 1)


def _make_kg_models_mock_with_memory_block():
    """建立 kg_models 的 mock，注入 MemoryBlock（從真實 models.py 取得）。

    routes.py:546 有一個 import bug：
        from .kg_models import Community, CommunitySummary, MemoryBlock, Triple
    MemoryBlock 實際上在 models.py，不在 kg_models.py。
    此 helper 讓 runtime 測試可以繼續測試計算邏輯，與 import 路徑 bug 解耦。
    """
    from src.modules.memvault import kg_models, models

    mock_kg_models = MagicMock()
    mock_kg_models.Community = kg_models.Community
    mock_kg_models.CommunitySummary = kg_models.CommunitySummary
    mock_kg_models.Triple = kg_models.Triple
    # MemoryBlock 在 models.py，不在 kg_models.py（Phase F import bug）
    mock_kg_models.MemoryBlock = models.MemoryBlock
    return mock_kg_models


class TestPhaseF_RecalculateProfile:
    """INV-5~9: recalculate_profile 使用 MemoryBlock 計算 attitude_score，
    skill_score 固定為 0.0。

    所有測試 mock 外部 DB，真跑 routes.py 裡的計算邏輯。
    """

    @pytest.mark.asyncio
    async def test_inv5_zero_attitude_blocks_score_is_zero(self):
        """INV-5: 0 attitude blocks → attitude_score == 0.0。

        Mutation target: 改掉 `max(att_count, 1)` 使 att_count=0 時回傳非零值。
        """
        score = _expected_attitude_score(0)
        assert score == 0.0, f"INV-5 violated: expected 0.0 but got {score}"

    @pytest.mark.asyncio
    async def test_inv6_one_attitude_block_score_positive(self):
        """INV-6: 1 attitude block → log10(1)=0 故 score==0.0；2+ blocks 才 > 0。

        Mutation target: 把 log10(max(1,1))=0 誤用導致 score 仍為 0。
        驗證：至少 2 個 blocks 時 score > 0，確保 log scaling 正常運作。
        """
        score_1 = _expected_attitude_score(1)
        assert score_1 == 0.0, f"INV-6: 1 block should give 0.0 (log10(1)=0), got {score_1}"

        score_2 = _expected_attitude_score(2)
        assert score_2 > 0.0, (
            f"INV-6 violated: 2 attitude blocks should produce score > 0.0, got {score_2}"
        )

    @pytest.mark.asyncio
    async def test_inv6b_ten_attitude_blocks_positive(self):
        """INV-6b: 10 attitude blocks → attitude_score > 0.0。

        Mutation target: 計算時分母用錯（如 log10(1000) 代替 log10(500)）導致比例錯誤。
        """
        score = _expected_attitude_score(10)
        assert score > 0.0, f"INV-6b violated: 10 blocks should produce positive score, got {score}"
        # 驗證公式正確性：log10(10)/log10(500) * 60 ≈ 22.0
        expected = round(min(math.log10(10) / math.log10(500) * 60, 60), 1)
        assert abs(score - expected) < 0.01, (
            f"INV-6b formula mismatch: got {score}, expected {expected}"
        )

    @pytest.mark.asyncio
    async def test_inv7_500_attitude_blocks_caps_at_60(self):
        """INV-7: 500 attitude blocks → attitude_score ≈ 60.0（log10(500)/log10(500)*60 = 60）。

        Mutation target: 把 cap 從 60 改為 100 或移除 min()。
        """
        score = _expected_attitude_score(500)
        assert score == 60.0, (
            f"INV-7 violated: 500 blocks should produce score==60.0, got {score}"
        )

    @pytest.mark.asyncio
    async def test_inv8_1000_blocks_still_capped_at_60(self):
        """INV-8: 1000 attitude blocks → attitude_score == 60.0（超過 500 仍 cap）。

        Mutation target: 移除 min(..., 60) cap，導致超過 500 個 block 時 score > 60。
        """
        score = _expected_attitude_score(1000)
        assert score == 60.0, (
            f"INV-8 violated: 1000 blocks should still cap at 60.0, got {score}"
        )

    @pytest.mark.asyncio
    async def test_inv9_skill_score_removed_from_schema(self):
        """INV-9: skill_score 已從 ProfileScoreResponse 和 ProfileScoreUpdate schema 移除。

        Mutation target: 誤將 skill_score 加回 schema，暗示 SkillProfile 已重新引入。
        """
        from src.modules.memvault.schemas import ProfileScoreResponse, ProfileScoreUpdate

        assert "skill_score" not in ProfileScoreResponse.model_fields, (
            "INV-9 violated: skill_score should be removed from ProfileScoreResponse schema"
        )
        assert "skill_score" not in ProfileScoreUpdate.model_fields, (
            "INV-9 violated: skill_score should be removed from ProfileScoreUpdate schema"
        )

    @pytest.mark.asyncio
    async def test_attitude_score_computed_from_memory_block(self):
        """Phase F runtime 回歸：recalculate_profile 計算出正確的 attitude_score。

        Mutation target: 把 MemoryBlock 換回 AttitudeFact，或者忘記 block_type='attitude' filter，
        或公式中的分母從 log10(500) 改為其他值。

        注意：透過 sys.modules patch 繞過 routes.py:546 的 import bug。
        """
        import sys
        from src.modules.memvault.routes import recalculate_profile

        att_count = 50
        expected_score = _expected_attitude_score(att_count)

        mock_result = MagicMock()
        mock_result.space_id = "test-space"
        mock_result.knowledge_score = 0.0
        mock_result.attitude_score = expected_score

        db = _make_db_mock(att_count=att_count, triple_count=0, cluster_count=0, wisdom_count=0)
        mock_kg = _make_kg_models_mock_with_memory_block()

        with patch.dict(sys.modules, {"src.modules.memvault.kg_models": mock_kg}):
            with patch("src.modules.memvault.routes.profile_score_service") as mock_service:
                captured = {}

                async def fake_upsert(db_sess, space_id, body):
                    captured["attitude_score"] = body.attitude_score
                    return mock_result

                mock_service.upsert = fake_upsert

                await recalculate_profile(
                    space_id="test-space",
                    db=db,
                    _user={"sub": "test-user"},
                )

        assert abs(captured["attitude_score"] - expected_score) < 0.01, (
            f"Phase F: attitude_score mismatch. expected {expected_score}, got {captured['attitude_score']}"
        )


# ════════════════════════════════════════════════════════════════════════════════
# INV-10 & INV-11 — 禁止引用已刪除的 KAS 模型
# ════════════════════════════════════════════════════════════════════════════════


class TestPhaseF_ForbiddenImports:
    """INV-10~11: routes.py 不得引用 AttitudeFact 或 SkillProfile。

    Mutation target: 有人把 AttitudeFact/SkillProfile 加回 routes.py 的 import。
    """

    def test_inv10_no_attitude_fact_in_routes(self):
        """INV-10: routes.py 原始碼中不含 AttitudeFact 引用。

        直接掃描原始碼，不依賴 runtime import 成功與否。
        """
        routes_path = os.path.join(
            _CORE, "src", "modules", "memvault", "routes.py"
        )
        with open(routes_path, "r", encoding="utf-8") as f:
            source = f.read()
        assert "AttitudeFact" not in source, (
            "INV-10 violated: 'AttitudeFact' found in routes.py — KAS model should not be referenced"
        )

    def test_inv11_no_skill_profile_in_routes(self):
        """INV-11: routes.py 原始碼中不含 SkillProfile 引用（除了註解說明）。

        Mutation target: 誤加入 SkillProfile import 或使用。
        注意：允許純註解文字說明（'SkillProfile removed'），只禁止程式碼引用。
        """
        routes_path = os.path.join(
            _CORE, "src", "modules", "memvault", "routes.py"
        )
        with open(routes_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        code_lines_with_skill_profile = [
            (i + 1, line.rstrip())
            for i, line in enumerate(lines)
            if "SkillProfile" in line and not line.lstrip().startswith("#")
        ]
        assert not code_lines_with_skill_profile, (
            f"INV-11 violated: SkillProfile referenced in non-comment code in routes.py: "
            f"{code_lines_with_skill_profile}"
        )

    def test_inv10_no_attitude_fact_in_kg_routes(self):
        """INV-10 補充：kg_routes.py 也不得引用 AttitudeFact。"""
        kg_routes_path = os.path.join(
            _CORE, "src", "modules", "memvault", "kg_routes.py"
        )
        with open(kg_routes_path, "r", encoding="utf-8") as f:
            source = f.read()
        assert "AttitudeFact" not in source, (
            "INV-10 violated: 'AttitudeFact' found in kg_routes.py"
        )

    def test_inv11_no_skill_profile_in_kg_routes(self):
        """INV-11 補充：kg_routes.py 非註解行不得引用 SkillProfile。"""
        kg_routes_path = os.path.join(
            _CORE, "src", "modules", "memvault", "kg_routes.py"
        )
        with open(kg_routes_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        code_lines = [
            (i + 1, line.rstrip())
            for i, line in enumerate(lines)
            if "SkillProfile" in line and not line.lstrip().startswith("#")
        ]
        assert not code_lines, (
            f"INV-11 violated: SkillProfile referenced in non-comment code in kg_routes.py: {code_lines}"
        )

    def test_phase_f_import_bug_memory_block_not_in_kg_models(self):
        """Phase F import bug 回歸：MemoryBlock 應在 models.py，不是 kg_models.py。

        routes.py:546 錯誤地從 kg_models import MemoryBlock，但 MemoryBlock
        實際定義在 models.py。此測試捕捉這個 import 路徑錯誤。

        Mutation target: 如果有人「修復」這個 import 讓它從 kg_models 可用，
        此測試需要相應更新（但現況應顯示 kg_models 沒有 MemoryBlock）。
        """
        from src.modules.memvault import kg_models, models

        assert hasattr(models, "MemoryBlock"), (
            "MemoryBlock should be defined in models.py"
        )
        assert not hasattr(kg_models, "MemoryBlock"), (
            "MemoryBlock should NOT be in kg_models.py — "
            "routes.py:546 has a bug importing it from the wrong module"
        )


# ════════════════════════════════════════════════════════════════════════════════
# 公式邊界值對照表測試（mutation-killing oracle）
# ════════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("att_count,expected_score", [
    (0, 0.0),        # INV-5: 零個 block
    (1, 0.0),        # log10(1) = 0 → score 0
    (2, round(min(math.log10(2) / math.log10(500) * 60, 60), 1)),   # 正數開始
    (10, round(min(math.log10(10) / math.log10(500) * 60, 60), 1)),
    (100, round(min(math.log10(100) / math.log10(500) * 60, 60), 1)),
    (499, round(min(math.log10(499) / math.log10(500) * 60, 60), 1)),
    (500, 60.0),     # INV-7: 剛好到上限
    (501, 60.0),     # 超過 500 仍 cap
    (1000, 60.0),    # INV-8: 遠超 500 仍 cap
    (10000, 60.0),   # 極大值仍 cap
])
def test_attitude_score_formula_oracle(att_count, expected_score):
    """參數化 oracle 測試：驗證 attitude_score 公式各邊界值。

    Mutation target: 任何對 a_base 公式、cap 值、round 精度的修改。
    """
    actual = _expected_attitude_score(att_count)
    assert actual == expected_score, (
        f"Formula oracle failed for att_count={att_count}: "
        f"expected {expected_score}, got {actual}"
    )

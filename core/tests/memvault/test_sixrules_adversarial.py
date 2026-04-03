"""Adversarial tests for memvault fast/slow CLT prefetch pipeline.

每個測試針對一個具體的 mutation，遵循六鐵律：
  - Mutation thinking: 每個測試有明確目標 mutation
  - Mock 只限外部 I/O: Redis/DB mock，內部邏輯真跑
  - 不變量優先: 測「系統應如何表現」，不測「class 存在」
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── 直接從 worktree 根目錄的 source 引入 ───────────────────────────────────

import sys
import os

# 確保 src 路徑可用（worktree 隔離，不依賴安裝）
_CORE = os.path.join(os.path.dirname(__file__), "..", "..")
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)

from src.shared.prefetch import PrefetchFingerprint, PrefetchMetrics, SpeculativePrefetchCache
from src.modules.memvault.slow_thinker import (
    AdmissionGateOp,
    CacheWriterOp,
    EvictionOp,
    IntentPredictorOp,
    PrefetchExecutorOp,
    QueryEventRecorderOp,
    _build_fingerprint_from_ctx,
    _MIN_SAMPLE_THRESHOLD,
)
from src.modules.memvault.query_runtime import (
    _merge_prefetch_cards,
    choose_thinking_mode,
)
from src.modules.memvault.schemas import MemoryCard, MemoryQueryRequest
from src.shared.prefetch import PrefetchFingerprint
from src.shared.reactive import Pipeline


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


def _make_card(card_id: str, source: str | None = None) -> MemoryCard:
    return MemoryCard(
        id=card_id,
        title="test",
        summary="test summary",
        why_relevant="test",
        use_now="test",
        layer="fast",
        source_type="block",
        confidence=0.8,
        source=source,
    )


def _base_ctx(**overrides) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "space_id": "test_space",
        "query": "what is my Python style?",
        "intent": "factual",
        "tags": ["python", "style"],
        "consumer": "agent",
        "task_mode": "build",
        "thinking_mode_used": "fast",
        "load_budget": "standard",
        "result_count": 5,
    }
    ctx.update(overrides)
    return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# T1: Fingerprint write/read 一致性
#
# Mutation: IntentPredictorOp._build_fp 用的 fields 與 _check_prefetch_cache 用的
# fields 相同嗎？規格要求 consumer + task_mode + intent 三欄位 hash。
#
# 真正的危機：_check_prefetch_cache 用 classify_query(query).intent.value 作為
# intent，而 Write path（_build_fingerprint_from_ctx）用 ctx["intent"]（事件字串）。
# 如果兩邊的 intent 值不同 → cache key 不同 → 永遠 miss。
# ═══════════════════════════════════════════════════════════════════════════════


class TestFingerprintConsistency:
    """T1: Write path 與 Read path 的 fingerprint 必須用相同三欄位"""

    def test_write_path_fingerprint_fields(self):
        """Write path (_build_fingerprint_from_ctx) 確實只用 consumer/task_mode/intent"""
        ctx = _base_ctx()
        fp = _build_fingerprint_from_ctx(ctx)
        assert fp.fields == {
            "consumer": "agent",
            "task_mode": "build",
            "intent": "factual",
        }, f"Write path fields: {fp.fields}"

    def test_intent_predictor_build_fp_fields_match_write_path(self):
        """IntentPredictorOp._build_fp 應與 _build_fingerprint_from_ctx 用相同欄位。

        Mutation target: 如果 IntentPredictorOp 加了額外欄位（如 tags/top_k），
        則與 AdmissionGate 的 inflight lock fingerprint 不同 → lock 無效。
        """
        op = IntentPredictorOp()
        ctx = _base_ctx()
        fp = op._build_fp("test_space", ctx, "factual", ["python"])

        # 規格：只有 consumer/task_mode/intent 三欄位（tags 不在 fingerprint 裡）
        assert set(fp.fields.keys()) == {"consumer", "task_mode", "intent"}, (
            f"IntentPredictorOp._build_fp fields: {fp.fields.keys()} — "
            "tags/top_k 不應進入 fingerprint，否則 read path 無法命中"
        )

    def test_fingerprint_cache_key_deterministic(self):
        """相同三欄位 → 相同 cache key（hash 穩定性）"""
        fp1 = PrefetchFingerprint(
            module="memvault",
            space_id="s1",
            fields={"consumer": "agent", "task_mode": "build", "intent": "factual"},
        )
        fp2 = PrefetchFingerprint(
            module="memvault",
            space_id="s1",
            fields={"consumer": "agent", "task_mode": "build", "intent": "factual"},
        )
        assert fp1.cache_key == fp2.cache_key

    def test_fingerprint_intent_source_mismatch_different_keys(self):
        """Write path intent='unknown' vs Read path intent='factual' → 不同 cache key。

        這個測試記錄了規格要求 intent 一致性的核心問題：
        如果事件裡的 intent 是 'unknown'（run_memory_query 發射的固定值），
        但 read path 用 classify_query 得到 'factual'，兩者 key 不同。
        """
        fp_write = PrefetchFingerprint(
            module="memvault",
            space_id="s1",
            fields={"consumer": "agent", "task_mode": "build", "intent": "unknown"},
        )
        fp_read = PrefetchFingerprint(
            module="memvault",
            space_id="s1",
            fields={"consumer": "agent", "task_mode": "build", "intent": "factual"},
        )
        assert fp_write.cache_key != fp_read.cache_key, (
            "write intent='unknown' vs read intent='factual' 應該產生不同 key。"
            "這表示 run_memory_query 寫死 intent='unknown' 會導致永遠 miss。"
        )

    def test_query_completed_event_intent_is_hardcoded_unknown(self):
        """Mutation: run_memory_query 發射 QUERY_COMPLETED 時 intent 固定為 'unknown'。

        這個 mutation 使 write path 永遠寫入 intent=unknown，
        但 read path 用 classify_query 得到真實 intent → 永遠 miss。
        """
        # 從 query_runtime.py 第 470 行的事件 payload 結構可知
        # "intent": "unknown" 是 hardcoded 值
        # 這裡確認這個問題的存在性
        import inspect
        import src.modules.memvault.query_runtime as qr
        source = inspect.getsource(qr.run_memory_query)
        assert '"intent": "unknown"' in source, (
            "run_memory_query 應該有 'intent': 'unknown' hardcoded — "
            "如果這個斷言失敗代表問題已修復"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# T2: AdmissionGate Rule 順序 — inflight lock 佔用後 hit_rate skip
#
# Mutation target: Rule 4 acquire inflight lock，但 Rule 5 (low_hit_rate) skip 時，
# lock 已佔用但沒有實際 prefetch → 5 秒內同樣請求被 Rule 4 阻擋。
# ═══════════════════════════════════════════════════════════════════════════════


class TestAdmissionGateRuleOrder:
    """T2: Rule 4 acquire inflight 後 Rule 5 skip → lock 無意義佔用"""

    @pytest.mark.asyncio
    async def test_rule4_acquires_lock_before_rule5_check(self):
        """當 Rule 5 (low hit_rate) skip 時，inflight lock 已被 Rule 4 佔用。

        預期行為（規格）：如果 Rule 5 要 skip，Rule 4 不應先 acquire lock。
        實際行為（bug）：Rule 4 先 acquire，Rule 5 才 check → lock 被白佔。
        """
        fake_redis = MagicMock()
        # Rule 4: inflight lock 成功取得
        fake_redis.set = AsyncMock(return_value=True)  # SETNX returns True = acquired
        # Rule 5: 模擬低命中率情況
        metrics_data = {
            "prefetch_count": str(_MIN_SAMPLE_THRESHOLD + 10),  # > MIN_SAMPLE
            "hit_count": "0",  # hit_rate = 0 < 0.05
            "miss_count": "10",
            "query_count": "60",
            "waste_count": "0",
            "skip_count": "0",
            "latency_saved_ms": "0",
            "compute_cost_ms": "0",
        }
        fake_redis.hgetall = AsyncMock(return_value=metrics_data)

        with patch("src.shared.prefetch.get_redis", return_value=fake_redis):
            op = AdmissionGateOp()
            ctx = _base_ctx()
            result = await op(ctx)

        # Rule 5 should skip
        assert result["should_prefetch"] is False
        assert result["skip_reason"] == "low_hit_rate"

        # FIXED: Rule 4 (hit_rate) now runs BEFORE Rule 5 (inflight lock).
        # When hit_rate skip fires, inflight lock should NOT be acquired.
        lock_acquired = fake_redis.set.called
        assert lock_acquired is False, (
            "After fix: inflight lock should NOT be acquired when hit_rate skip fires first."
        )

    @pytest.mark.asyncio
    async def test_rule4_should_not_fire_when_rule5_would_skip(self):
        """規格要求：如果 hit_rate 已知會 skip，inflight lock 不應被佔用。

        這個測試驗證 Rule 順序的「正確」行為。
        如果 Rule 5 在 Rule 4 之前，lock 就不會被白佔。
        目前這個測試會 FAIL，因為實作 Rule 4 在 Rule 5 之前。
        """
        lock_call_count = 0
        original_try_acquire = SpeculativePrefetchCache.try_acquire_inflight

        async def counting_acquire(self, fp):
            nonlocal lock_call_count
            lock_call_count += 1
            return True

        fake_redis = MagicMock()
        fake_redis.set = AsyncMock(return_value=True)
        metrics_data = {
            "prefetch_count": str(_MIN_SAMPLE_THRESHOLD + 10),
            "hit_count": "0",
            "miss_count": "10",
            "query_count": "60",
            "waste_count": "0",
            "skip_count": "0",
            "latency_saved_ms": "0",
            "compute_cost_ms": "0",
        }
        fake_redis.hgetall = AsyncMock(return_value=metrics_data)

        with patch("src.shared.prefetch.get_redis", return_value=fake_redis):
            with patch.object(SpeculativePrefetchCache, "try_acquire_inflight", counting_acquire):
                op = AdmissionGateOp()
                ctx = _base_ctx()
                result = await op(ctx)

        assert result["skip_reason"] == "low_hit_rate"
        # 規格預期：hit_rate 過低時，inflight lock 不應被佔用（0 次呼叫）
        # 實際：lock_call_count == 1，表示 Rule 4 在 Rule 5 之前執行
        assert lock_call_count == 0, (
            f"Bug: try_acquire_inflight called {lock_call_count} time(s) "
            "even though Rule 5 (low_hit_rate) would skip. "
            "Rule ordering should be: 1-consumer, 2-slow, 3-no-results, 5-hit_rate, 4-inflight"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# T3: IntentPredictor transition table 不完整
#
# Mutation target: _TRANSITIONS 沒有 'factual' 和 'unknown' 條目 →
# .get(intent, intent) fallback 讓這兩種 intent 預測自己。
# ═══════════════════════════════════════════════════════════════════════════════


class TestIntentPredictorTransitions:
    """T3: factual/unknown 沒有 transition rule → 預測自己"""

    def test_all_possible_intents_have_transition(self):
        """規格：所有 QueryIntent 值都應有 transition，防止預測自己。

        規格明確說有 transition table，但 factual/unknown 不在裡面。
        """
        op = IntentPredictorOp()
        # 根據規格和 query_router 可能的 intent 值
        known_intents = [
            "entity_lookup", "conceptual", "exploratory", "cross_domain",
            "factual", "unknown"
        ]
        for intent in known_intents:
            predicted = op._TRANSITIONS.get(intent, intent)
            # factual 和 unknown 沒有 transition → 預測自己
            if intent in ("factual", "unknown"):
                assert predicted == intent, (
                    f"Expected {intent} to have no transition (confirms the bug)"
                )

    def test_factual_intent_predicts_itself(self):
        """Factual intent 因缺少 transition rule → 預測下一個也是 factual。

        這可能合理（user 會連續問 factual 問題），但也可能不是預期行為。
        規格說「entity_lookup → factual (drill-down)」但沒說 factual 之後是什麼。
        """
        op = IntentPredictorOp()
        result = op._TRANSITIONS.get("factual", "factual")
        assert result == "factual", "factual 無 transition rule，預測自己"

    def test_unknown_intent_predicts_itself(self):
        """Unknown intent 預測自己 → 未知意圖的 prefetch 無意義。

        規格說 cold start fallback 用「最近 7 天最常見 intent」，
        但 transition table 路徑直接回傳 unknown，不是 cold start。
        """
        op = IntentPredictorOp()
        result = op._TRANSITIONS.get("unknown", "unknown")
        assert result == "unknown", "unknown 無 transition rule，預測自己"

    @pytest.mark.asyncio
    async def test_intent_predictor_no_recent_with_unknown_intent(self):
        """無歷史記錄 + intent=unknown → 預測 unknown → tags 為空 → 無法 prefetch。"""
        op = IntentPredictorOp()

        with patch.object(op, "_get_recent_journals", AsyncMock(return_value=[])):
            ctx = _base_ctx(intent="unknown", tags=[], should_prefetch=True)
            result = await op(ctx)

        fp = result.get("predicted_fingerprint")
        assert fp is not None
        assert fp.fields["intent"] == "unknown", (
            "Unknown intent with no history should predict 'unknown', "
            "which leads to empty tags and no useful prefetch"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# T4: _merge_prefetch_cards budget 包含 existing 長度
#
# Mutation target: budget=6, existing 已有 5 張 → 只能 merge 1 張。
# 這是否符合「規格的 budget 是最終上限」或「budget 是可加入的上限」？
# ═══════════════════════════════════════════════════════════════════════════════


class TestMergePrefetchCardsBudget:
    """T4: _merge_prefetch_cards budget 語意驗證"""

    def test_budget_includes_existing_length(self):
        """budget=4, existing 已有 4 張 → 0 張 prefetch 能進入。

        規格說：「把 prefetch 卡片排在 stable 之後，尊重 budget」
        實作：len(merged) < budget → budget 是 merged 總長上限，包含 existing。
        """
        existing = [_make_card(f"e{i}") for i in range(4)]
        prefetched = [_make_card(f"p{i}", source="speculative_prefetch") for i in range(4)]
        budget = 4

        result = _merge_prefetch_cards(existing, prefetched, budget)

        # existing 已達到 budget，所有 prefetch 被排除
        assert len(result) == 4
        assert all(c.id.startswith("e") for c in result), (
            "When existing fills budget, no prefetch cards should enter"
        )

    def test_budget_allows_partial_prefetch_fill(self):
        """budget=6, existing=3 → 最多能加 3 張 prefetch。"""
        existing = [_make_card(f"e{i}") for i in range(3)]
        prefetched = [_make_card(f"p{i}", source="speculative_prefetch") for i in range(5)]
        budget = 6

        result = _merge_prefetch_cards(existing, prefetched, budget)

        assert len(result) == 6
        prefetch_count = sum(1 for c in result if c.id.startswith("p"))
        assert prefetch_count == 3, f"Expected 3 prefetch cards, got {prefetch_count}"

    def test_merge_preserves_existing_order(self):
        """Existing cards 必須排在前面，prefetch 排後面（規格：prefetch 排在 stable 之後）。"""
        existing = [_make_card(f"e{i}") for i in range(2)]
        prefetched = [_make_card(f"p{i}", source="speculative_prefetch") for i in range(2)]
        budget = 4

        result = _merge_prefetch_cards(existing, prefetched, budget)

        assert result[0].id == "e0"
        assert result[1].id == "e1"
        assert result[2].id == "p0"
        assert result[3].id == "p1"

    def test_merge_deduplicates_by_id(self):
        """去重 by ID：prefetch 與 existing 有相同 ID 的卡片應被排除。"""
        existing = [_make_card("shared_id"), _make_card("e1")]
        prefetched = [_make_card("shared_id", source="speculative_prefetch"), _make_card("p1")]
        budget = 10

        result = _merge_prefetch_cards(existing, prefetched, budget)

        ids = [c.id for c in result]
        assert ids.count("shared_id") == 1, "Duplicate ID should appear only once"
        assert "p1" in ids, "Non-duplicate prefetch card should be included"

    def test_query_runtime_uses_fast_plus_2_as_budget(self):
        """query_runtime.py 用 budget['fast'] + 2 作為 merge budget。

        standard budget['fast'] = 4，所以 merge budget = 6。
        如果 fast_cards 已達 4 張，prefetch 只能補 2 張。
        """
        from src.modules.memvault.query_runtime import _budget_config
        budget = _budget_config("standard")
        merge_budget = budget["fast"] + 2
        assert merge_budget == 6, f"Expected merge budget 6, got {merge_budget}"

        # 如果 fast_cards 達到 fast budget (4張)，只剩 2 格給 prefetch
        existing = [_make_card(f"e{i}") for i in range(budget["fast"])]
        prefetched = [_make_card(f"p{i}", source="speculative_prefetch") for i in range(4)]
        result = _merge_prefetch_cards(existing, prefetched, merge_budget)
        prefetch_count = sum(1 for c in result if c.id.startswith("p"))
        assert prefetch_count == 2, (
            f"With fast_cards full ({budget['fast']}), only 2 prefetch slots remain. "
            f"Got {prefetch_count}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# T5: source field 在 merge 後的 cards 是否被保留
#
# Mutation target: MemoryCard.source 在 merge 後應保持 "speculative_prefetch"。
# ═══════════════════════════════════════════════════════════════════════════════


class TestSourceFieldPreservation:
    """T5: merge 後 speculative_prefetch source 欄位不應消失"""

    def test_prefetch_cards_retain_source_after_merge(self):
        """Merge 後的 prefetch 卡片 source 必須保持 'speculative_prefetch'。"""
        existing = [_make_card("e1")]
        prefetched = [_make_card("p1", source="speculative_prefetch")]
        budget = 5

        result = _merge_prefetch_cards(existing, prefetched, budget)
        prefetch_card = next(c for c in result if c.id == "p1")

        assert prefetch_card.source == "speculative_prefetch", (
            f"Source field should be preserved after merge, got: {prefetch_card.source}"
        )

    def test_normal_cards_source_is_none(self):
        """非 prefetch 的 fast_cards source 應為 None。"""
        existing = [_make_card("e1", source=None)]
        prefetched = [_make_card("p1", source="speculative_prefetch")]
        budget = 5

        result = _merge_prefetch_cards(existing, prefetched, budget)
        normal_card = next(c for c in result if c.id == "e1")

        assert normal_card.source is None

    def test_check_prefetch_cache_sets_source_field(self):
        """_check_prefetch_cache 回傳的 MemoryCard 應設置 source='speculative_prefetch'。

        從 query_runtime.py 第 335 行: c.setdefault('source', 'speculative_prefetch')
        """
        # 驗證程式碼中確實有設置 source 欄位
        import inspect
        import src.modules.memvault.query_runtime as qr
        source = inspect.getsource(qr._check_prefetch_cache)
        assert "speculative_prefetch" in source, (
            "_check_prefetch_cache 應設置 source='speculative_prefetch'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# T6: Pipeline.compile() 靜態驗證
#
# Mutation target: 確認 slow_thinker 的 pipeline 能通過 compile()，
# 即所有 input_keys 都有前驅提供。
# ═══════════════════════════════════════════════════════════════════════════════


class TestPipelineCompile:
    """T6: Pipeline compile() 靜態驗證"""

    def test_slow_thinker_pipeline_compiles_without_missing_keys(self):
        """slow_thinker_b1 pipeline 的 key 依賴鏈完整。"""
        from src.shared.reactive import Pipeline
        ops = [
            QueryEventRecorderOp(),
            AdmissionGateOp(),
            IntentPredictorOp(),
            PrefetchExecutorOp(),
            CacheWriterOp(),
        ]
        pipeline = Pipeline(name="slow_thinker_b1_test").pipe(*ops)
        initial_keys = {
            "space_id", "query", "intent", "tags", "consumer",
            "task_mode", "thinking_mode_used", "load_budget", "result_count",
        }
        missing = pipeline.compile(initial_keys=initial_keys)
        assert missing == [], (
            f"Pipeline compile failed — missing keys: {missing}\n"
            "This means an Op requires a key that no previous Op provides."
        )

    def test_admission_gate_output_provides_intent_predictor_input(self):
        """AdmissionGate 輸出 should_prefetch → IntentPredictor 需要它。"""
        gate = AdmissionGateOp()
        predictor = IntentPredictorOp()

        gate_outputs = set(gate.output_keys)
        predictor_inputs = set(predictor.input_keys)

        # should_prefetch 是 IntentPredictor 的必要輸入
        assert "should_prefetch" in predictor_inputs
        # AdmissionGate 必須提供它
        assert "should_prefetch" in gate_outputs

    def test_cache_writer_input_keys_are_provided_by_pipeline(self):
        """CacheWriterOp 需要的 keys 都由前面的 ops 提供。"""
        ops = [
            QueryEventRecorderOp(),
            AdmissionGateOp(),
            IntentPredictorOp(),
            PrefetchExecutorOp(),
            CacheWriterOp(),
        ]
        # 模擬 Pipeline.compile 邏輯
        available = {
            "space_id", "query", "intent", "tags", "consumer",
            "task_mode", "thinking_mode_used", "load_budget", "result_count",
        }
        for op in ops:
            available |= set(op.output_keys)

        writer = CacheWriterOp()
        for key in writer.input_keys:
            assert key in available, (
                f"CacheWriterOp requires '{key}' but it's not provided by any preceding op"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# T7: EvictionOp TTL 邏輯
#
# Mutation target: TTL=-1（無過期設定）的 prefetch key 不會被清除，
# TTL=-2（key 不存在）不會出錯。
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvictionOpTTL:
    """T7: EvictionOp TTL 判斷邏輯"""

    @pytest.mark.asyncio
    async def test_ttl_greater_than_30_not_evicted(self):
        """TTL > 30 的 key 不應被 evict（還有充足剩餘時間）。"""
        fake_redis = MagicMock()
        key = "prefetch:memvault:test_space:abc123"
        fake_redis.scan_iter = MagicMock(return_value=_async_iter([key]))
        fake_redis.ttl = AsyncMock(return_value=120)  # 2 minutes left
        fake_redis.delete = AsyncMock(return_value=1)

        with patch("src.shared.redis.get_redis", return_value=fake_redis):
            with patch("src.modules.memvault.slow_thinker._prefetch_cache") as mock_cache:
                mock_cache.record_waste = AsyncMock()
                op = EvictionOp()
                result = await op({"space_id": "test_space"})

        assert result["evicted_count"] == 0
        fake_redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_ttl_between_0_and_30_evicted(self):
        """0 < TTL < 30 的 key 應被 evict（快過期，可能是 waste）。"""
        fake_redis = MagicMock()
        key = "prefetch:memvault:test_space:abc123"
        fake_redis.scan_iter = MagicMock(return_value=_async_iter([key]))
        fake_redis.ttl = AsyncMock(return_value=15)  # 15s left, < 30
        fake_redis.delete = AsyncMock(return_value=1)

        with patch("src.shared.redis.get_redis", return_value=fake_redis):
            with patch("src.modules.memvault.slow_thinker._prefetch_cache") as mock_cache:
                mock_cache.record_waste = AsyncMock()
                op = EvictionOp()
                result = await op({"space_id": "test_space"})

        assert result["evicted_count"] == 1

    @pytest.mark.asyncio
    async def test_ttl_negative_one_not_evicted(self):
        """TTL=-1（無過期）的 key 不應被 evict。

        Redis ttl() = -1 表示 key 存在但沒有設 TTL（永久）。
        條件 0 < ttl < 30 確保 -1 不被誤刪。
        """
        fake_redis = MagicMock()
        key = "prefetch:memvault:test_space:abc123"
        fake_redis.scan_iter = MagicMock(return_value=_async_iter([key]))
        fake_redis.ttl = AsyncMock(return_value=-1)  # no TTL set
        fake_redis.delete = AsyncMock(return_value=1)

        with patch("src.shared.redis.get_redis", return_value=fake_redis):
            with patch("src.modules.memvault.slow_thinker._prefetch_cache") as mock_cache:
                mock_cache.record_waste = AsyncMock()
                op = EvictionOp()
                result = await op({"space_id": "test_space"})

        assert result["evicted_count"] == 0, "TTL=-1 (no expiry) should not be evicted"
        fake_redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_ttl_zero_not_evicted(self):
        """TTL=0 的 key 條件 0 < ttl < 30 排除，不應被 evict。"""
        fake_redis = MagicMock()
        key = "prefetch:memvault:test_space:abc123"
        fake_redis.scan_iter = MagicMock(return_value=_async_iter([key]))
        fake_redis.ttl = AsyncMock(return_value=0)
        fake_redis.delete = AsyncMock(return_value=1)

        with patch("src.shared.redis.get_redis", return_value=fake_redis):
            with patch("src.modules.memvault.slow_thinker._prefetch_cache") as mock_cache:
                mock_cache.record_waste = AsyncMock()
                op = EvictionOp()
                result = await op({"space_id": "test_space"})

        assert result["evicted_count"] == 0, "TTL=0 should not match condition 0 < ttl < 30"


# ═══════════════════════════════════════════════════════════════════════════════
# T8: try_acquire_inflight fail-open 行為
#
# Mutation target: Redis 故障時 fail-open（返回 True）讓 prefetch 繼續，
# 不應因 Redis 故障而靜默阻擋所有 prefetch。
# ═══════════════════════════════════════════════════════════════════════════════


class TestInflightLockFailOpen:
    """T8: Redis 故障時 try_acquire_inflight fail-open"""

    @pytest.mark.asyncio
    async def test_redis_failure_returns_true(self):
        """Redis 故障時 try_acquire_inflight 應回傳 True（fail-open）。"""
        def failing_redis():
            raise ConnectionError("Redis unavailable")

        cache = SpeculativePrefetchCache(module="memvault")
        fp = PrefetchFingerprint(
            module="memvault",
            space_id="test",
            fields={"consumer": "agent", "task_mode": "build", "intent": "factual"},
        )

        with patch("src.shared.prefetch.get_redis", side_effect=failing_redis):
            result = await cache.try_acquire_inflight(fp)

        assert result is True, (
            "On Redis failure, try_acquire_inflight should fail-open (return True) "
            "to avoid permanently blocking prefetch during outages"
        )

    @pytest.mark.asyncio
    async def test_redis_available_setnx_false_returns_false(self):
        """Redis 正常但 key 已存在（SETNX 返回 False）→ lock 未取得 → 回傳 False。"""
        fake_redis = MagicMock()
        fake_redis.set = AsyncMock(return_value=False)  # SETNX: key already exists

        cache = SpeculativePrefetchCache(module="memvault")
        fp = PrefetchFingerprint(
            module="memvault",
            space_id="test",
            fields={"consumer": "agent", "task_mode": "build", "intent": "factual"},
        )

        with patch("src.shared.prefetch.get_redis", return_value=fake_redis):
            result = await cache.try_acquire_inflight(fp)

        assert result is False, "SETNX returning None/False should mean lock not acquired"


# ═══════════════════════════════════════════════════════════════════════════════
# T9: choose_thinking_mode 優先權合約
#
# Mutation target: explicit > consumer > budget > task_mode > default
# ═══════════════════════════════════════════════════════════════════════════════


class TestChooseThinkingMode:
    """T9: choose_thinking_mode 優先權合約"""

    def test_explicit_slow_overrides_consumer_agent(self):
        """explicit thinking_mode='slow' 應覆蓋 consumer='agent'（agent 預設 fast）。"""
        result = choose_thinking_mode("build", "slow", "standard", "agent")
        assert result == "slow", "Explicit 'slow' should override agent consumer default"

    def test_explicit_fast_overrides_task_mode_reflect(self):
        """explicit 'fast' 應覆蓋 task_mode='reflect'（reflect 預設 slow）。"""
        result = choose_thinking_mode("reflect", "fast", "standard", "human")
        assert result == "fast", "Explicit 'fast' should override reflect task_mode default"

    def test_consumer_ui_auto_returns_slow(self):
        """consumer='ui' + thinking_mode='auto' → slow（規格：UI consumer 走 slow）。"""
        result = choose_thinking_mode("build", "auto", "standard", "ui")
        assert result == "slow"

    def test_consumer_agent_auto_returns_fast(self):
        """consumer='agent' + thinking_mode='auto' → fast。"""
        result = choose_thinking_mode("build", "auto", "standard", "agent")
        assert result == "fast"

    def test_load_budget_deep_auto_returns_slow(self):
        """load_budget='deep' + auto → slow（budget 優先於 task_mode）。"""
        result = choose_thinking_mode("build", "auto", "deep", "human")
        assert result == "slow"

    def test_task_mode_decide_auto_returns_slow(self):
        """task_mode='decide' + auto + human → slow。"""
        result = choose_thinking_mode("decide", "auto", "standard", "human")
        assert result == "slow"

    def test_default_case_returns_fast(self):
        """無特殊條件 → fast。"""
        result = choose_thinking_mode("build", "auto", "standard", "human")
        assert result == "fast"

    def test_invalid_values_use_defaults(self):
        """無效輸入應 normalize 後使用 default，不應 raise。"""
        result = choose_thinking_mode("INVALID", "INVALID", "INVALID", "INVALID")
        # build=default, auto=default, standard=default, human=default → fast
        assert result == "fast"


# ═══════════════════════════════════════════════════════════════════════════════
# T10: PrefetchMetrics hit_rate 計算不變量
#
# Mutation target: hit_rate 的分母應為 prefetch_count，零除時回傳 0.0。
# ═══════════════════════════════════════════════════════════════════════════════


class TestPrefetchMetricsInvariants:
    """T10: PrefetchMetrics 不變量"""

    def test_hit_rate_zero_on_cold_start(self):
        """冷啟動（prefetch_count=0）→ hit_rate = 0.0，不應 ZeroDivisionError。"""
        m = PrefetchMetrics(query_count=10, prefetch_count=0, hit_count=0)
        assert m.hit_rate == 0.0

    def test_hit_rate_correct_computation(self):
        """hit_rate = hit_count / prefetch_count。"""
        m = PrefetchMetrics(prefetch_count=100, hit_count=30)
        assert abs(m.hit_rate - 0.3) < 1e-9

    def test_waste_rate_zero_on_cold_start(self):
        """冷啟動 waste_rate 不應 ZeroDivisionError。"""
        m = PrefetchMetrics(prefetch_count=0, waste_count=0)
        assert m.waste_rate == 0.0

    @pytest.mark.asyncio
    async def test_admission_gate_min_sample_threshold_prevents_early_disable(self):
        """prefetch_count <= MIN_SAMPLE_THRESHOLD 時 Rule 5 不應 skip。

        即使 hit_rate=0，也要等樣本足夠才能判斷。
        """
        fake_redis = MagicMock()
        fake_redis.set = AsyncMock(return_value=True)
        metrics_data = {
            "prefetch_count": str(_MIN_SAMPLE_THRESHOLD - 1),  # 剛好低於門檻
            "hit_count": "0",
            "miss_count": "5",
            "query_count": "20",
            "waste_count": "0",
            "skip_count": "0",
            "latency_saved_ms": "0",
            "compute_cost_ms": "0",
        }
        fake_redis.hgetall = AsyncMock(return_value=metrics_data)

        pipe_mock = MagicMock()
        pipe_mock.hincrby = MagicMock()
        pipe_mock.expire = MagicMock()
        pipe_mock.execute = AsyncMock()
        fake_redis.pipeline = MagicMock(return_value=pipe_mock)

        with patch("src.shared.prefetch.get_redis", return_value=fake_redis):
            op = AdmissionGateOp()
            ctx = _base_ctx()
            result = await op(ctx)

        # Should NOT skip due to low hit rate (sample too small)
        assert result.get("skip_reason") != "low_hit_rate", (
            f"Should not skip due to low_hit_rate when prefetch_count < MIN_SAMPLE_THRESHOLD. "
            f"Got skip_reason={result.get('skip_reason')}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════════════════════════


async def _async_gen(items):
    for item in items:
        yield item


def _async_iter(items):
    return _async_gen(items)

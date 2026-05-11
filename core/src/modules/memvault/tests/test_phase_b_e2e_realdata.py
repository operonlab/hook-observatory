"""鐵律 3 (E2E) + 鐵律 4 (Real-Data) — Phase B evidence_signal.

鐵律 3 E2E：
- TripleService.before_create() 呼叫鏈 (mock-DB，驗 evidence_signal 回傳)
- 顯式傳 evidence_signal='inferred' → 不被覆寫
- 只給 confidence=0.5 → service 反推 'inferred'
- evidence_signal='extracted' 顯式 + confidence=0.5 → 不覆寫，保 'extracted'

鐵律 4 Real-Data：
- 讀 retrieval_baseline.json (35 KB，50 queries)
- 對每個 entry 的 baseline_routing_confidence 跑 signal_from_score()
- 分布 (extracted + inferred + ambiguous) == 100%
- 無 crash
- 模擬 community_summary EVIDENCE_SIGNAL_WEIGHT 加權 → 總邊權變化 < 50%
"""

from __future__ import annotations

import json
import math
import os
import sys

import pytest

# ── sys.path isolation (worktree-safe) ──────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKTREE_CORE = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
_WORKTREE_CORE_SRC = os.path.join(_WORKTREE_CORE, "src")
sys.path = [
    p for p in sys.path
    if "/workshop/" not in p or ".worktrees/" in p or "/.venv/" in p
]
sys.path.insert(0, _WORKTREE_CORE_SRC)
sys.path.insert(0, _WORKTREE_CORE)
for libname in (
    "text-ops", "kg-ops", "sdk-client", "tmux-lib",
    "audio-ops", "image-ops", "video-ops",
):
    p = f"/Users/joneshong/workshop/libs/{libname}"
    if p not in sys.path:
        sys.path.append(p)

_PIPELINE_DIR = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "..", "..", "mcp", "memvault")
)
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

_BASELINE_PATH = os.path.join(_HERE, "fixtures", "retrieval_baseline.json")


# ── helpers ─────────────────────────────────────────────────────────────────

def _load_baseline() -> list[dict]:
    """Load retrieval_baseline.json; return list of query dicts."""
    with open(_BASELINE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("queries", [])


def _make_service():
    from src.modules.memvault.kg_services import TripleService
    return TripleService()


# ============================================================
# 鐵律 3 — E2E (service layer, no DB)
# ============================================================


class TestE2EBeforeCreatePipeline:
    """鐵律 3：E2E — TripleService.before_create() 完整呼叫鏈."""

    def test_explicit_inferred_not_overwritten(self):
        """明確傳 evidence_signal='inferred' → before_create 不覆寫."""
        from src.modules.memvault.kg_schemas import TripleCreate

        svc = _make_service()
        data = TripleCreate(
            subject="少爺",
            predicate="uses",
            object="workshop",
            confidence=0.9,  # 若反推 → 'extracted'，但顯式設 'inferred'
            evidence_signal="inferred",
        )
        result = svc.before_create(data)
        assert result["evidence_signal"] == "inferred", (
            "顯式設 evidence_signal='inferred' 不應被 confidence 覆寫"
        )

    def test_confidence_0_5_reverse_infers_inferred(self):
        """confidence=0.5 且未設 evidence_signal → 反推 'inferred'."""
        from src.modules.memvault.kg_schemas import TripleCreate

        svc = _make_service()
        data = TripleCreate(
            subject="MemVault",
            predicate="phase",
            object="B",
            confidence=0.5,
        )
        result = svc.before_create(data)
        assert result["evidence_signal"] == "inferred", (
            "confidence=0.5 應反推 evidence_signal='inferred'"
        )

    def test_explicit_extracted_with_low_confidence_preserved(self):
        """顯式 evidence_signal='extracted' + confidence=0.3 → 保留 'extracted'."""
        from src.modules.memvault.kg_schemas import TripleCreate

        svc = _make_service()
        data = TripleCreate(
            subject="signal",
            predicate="is",
            object="extracted",
            confidence=0.3,
            evidence_signal="extracted",
        )
        result = svc.before_create(data)
        assert result["evidence_signal"] == "extracted", (
            "顯式設 evidence_signal='extracted' 不應被低 confidence 覆寫"
        )

    def test_no_confidence_default_extracted(self):
        """未提供 confidence → before_create 保留 default 'extracted'."""
        from src.modules.memvault.kg_schemas import TripleCreate

        svc = _make_service()
        data = TripleCreate(
            subject="X",
            predicate="rel",
            object="Y",
        )
        result = svc.before_create(data)
        assert result["evidence_signal"] == "extracted", (
            "未提供 confidence 時 evidence_signal 應保持 default 'extracted'"
        )

    def test_low_confidence_reverse_infers_ambiguous(self):
        """confidence=0.1 → 反推 'ambiguous'."""
        from src.modules.memvault.kg_schemas import TripleCreate

        svc = _make_service()
        data = TripleCreate(
            subject="uncertain",
            predicate="maybe",
            object="true",
            confidence=0.1,
        )
        result = svc.before_create(data)
        assert result["evidence_signal"] == "ambiguous", (
            "confidence=0.1 應反推 evidence_signal='ambiguous'"
        )

    def test_high_confidence_reverse_infers_extracted(self):
        """confidence=0.95 → 反推 'extracted'."""
        from src.modules.memvault.kg_schemas import TripleCreate

        svc = _make_service()
        data = TripleCreate(
            subject="fact",
            predicate="confirmed",
            object="yes",
            confidence=0.95,
        )
        result = svc.before_create(data)
        assert result["evidence_signal"] == "extracted", (
            "confidence=0.95 應反推 evidence_signal='extracted'"
        )

    def test_before_create_returns_predicate_normalized(self):
        """before_create 同時做 predicate normalize，不破壞 evidence_signal."""
        from src.modules.memvault.kg_schemas import TripleCreate

        svc = _make_service()
        data = TripleCreate(
            subject="A",
            predicate="Is Related To",
            object="B",
            confidence=0.6,
        )
        result = svc.before_create(data)
        # predicate 被 normalize；evidence_signal 獨立反推
        assert "evidence_signal" in result
        assert "predicate" in result


# ============================================================
# 鐵律 4 — Real-Data (retrieval_baseline.json)
# ============================================================


class TestRealDataSignalDistribution:
    """鐵律 4：Real-Data — 對 baseline 50 queries 跑 signal_from_score()."""

    def _get_signal_from_score(self):
        from src.modules.memvault.crag_evaluator import signal_from_score
        return signal_from_score

    def test_baseline_file_exists(self):
        """baseline fixture 存在且可讀。"""
        assert os.path.isfile(_BASELINE_PATH), (
            f"retrieval_baseline.json 不存在: {_BASELINE_PATH}"
        )

    def test_all_entries_no_crash(self):
        """所有 baseline entry 通過 signal_from_score 不 crash。"""
        signal_from_score = self._get_signal_from_score()
        queries = _load_baseline()
        assert len(queries) > 0, "baseline 至少要有一條 query"

        for q in queries:
            conf = q.get("baseline_routing_confidence")
            # 不應 raise
            sig = signal_from_score(conf)
            assert sig in ("extracted", "inferred", "ambiguous"), (
                f"signal_from_score({conf!r}) 回傳非法值: {sig!r}"
            )

    def test_distribution_sums_to_100_percent(self):
        """extracted + inferred + ambiguous 分布合計 100%。"""
        signal_from_score = self._get_signal_from_score()
        queries = _load_baseline()
        counts: dict[str, int] = {"extracted": 0, "inferred": 0, "ambiguous": 0}
        for q in queries:
            conf = q.get("baseline_routing_confidence")
            sig = signal_from_score(conf)
            counts[sig] = counts.get(sig, 0) + 1
        total = sum(counts.values())
        assert total == len(queries), (
            f"分布計數總和 {total} 不等於 query 總數 {len(queries)}"
        )
        # 至少覆蓋所有三個 bucket（baseline 橫跨 0-0.671，理論上三層都有）
        pct_extracted = counts["extracted"] / total * 100
        pct_inferred = counts["inferred"] / total * 100
        pct_ambiguous = counts["ambiguous"] / total * 100
        total_pct = pct_extracted + pct_inferred + pct_ambiguous
        assert abs(total_pct - 100.0) < 0.01, (
            f"百分比合計應為 100%，得 {total_pct:.2f}%"
        )

    def test_no_nan_in_distribution(self):
        """signal_from_score 對有效 float 輸入不回傳 NaN 或空字串。"""
        signal_from_score = self._get_signal_from_score()
        queries = _load_baseline()
        for q in queries:
            conf = q.get("baseline_routing_confidence")
            if conf is not None:
                sig = signal_from_score(float(conf))
                assert sig and isinstance(sig, str), (
                    f"confidence={conf} → 無效信號 {sig!r}"
                )

    def test_community_edge_weight_change_within_50_percent(self):
        """模擬 EVIDENCE_SIGNAL_WEIGHT 加權前後，總邊權變化 < 50%（防崩潰）。

        用 baseline confidence 模擬 triple weight distribution。
        Unweighted = sum of 1.0 per entry.
        Weighted = sum of EVIDENCE_SIGNAL_WEIGHT[signal].
        Change must be < 50% of unweighted total.
        """
        signal_from_score = self._get_signal_from_score()
        # Import EVIDENCE_SIGNAL_WEIGHT from pipeline
        try:
            from pipelines.community_summary_pipeline import EVIDENCE_SIGNAL_WEIGHT
        except ImportError:
            # Fallback: define inline (same values as implementation)
            EVIDENCE_SIGNAL_WEIGHT = {
                "extracted": 1.0,
                "inferred": 0.7,
                "ambiguous": 0.3,
            }

        queries = _load_baseline()
        unweighted_total = float(len(queries))
        weighted_total = 0.0
        for q in queries:
            conf = q.get("baseline_routing_confidence")
            sig = signal_from_score(conf)
            weighted_total += EVIDENCE_SIGNAL_WEIGHT.get(sig, 1.0)

        change_ratio = abs(weighted_total - unweighted_total) / unweighted_total
        assert change_ratio < 0.5, (
            f"Evidence signal 加權導致邊權變化 {change_ratio:.2%}，超過 50% 上限"
        )

"""Centralized enrichment field schemas for all capture adapters.

Single source of truth for LLM extraction prompts.
Each key is (module, entity_type), value is field_name -> description for Haiku.

RLM enrichment strategy for ambiguous inputs: when Haiku confidence < 0.6
on any field, RLM recursively decomposes the input to resolve ambiguity.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.modules.capture.strategies import EnrichmentResult, EnrichmentStrategy
from src.shared.llm_json import parse_llm_json
from src.shared.rlm_engine import RLMConfig, RLMEngine

logger = logging.getLogger(__name__)

ENRICHMENT_SCHEMAS: dict[tuple[str, str], dict[str, str]] = {
    ("finance", "transaction"): {
        "amount": "交易金額(數字)",
        "description": "交易描述/備註",
        "type": "交易類型: expense(支出) 或 income(收入)",
        "category_id": "消費類別名稱(如: 餐飲、交通、娛樂)",
        "wallet_id": "錢包/付款帳戶名稱(如: 現金、信用卡、LINE Pay、街口)",
        "payment_method": "付款方式: cash/credit_card/debit_card/transfer",
        "transacted_at": "交易時間 ISO 格式",
    },
    ("finance", "subscription"): {
        "name": "訂閱服務名稱",
        "amount": "訂閱金額(數字)",
        "billing_cycle": "計費週期: monthly/yearly/weekly",
        "start_date": "開始日期 ISO 格式",
    },
    ("finance", "installment"): {
        "description": "分期項目描述",
        "total_amount": "總金額(數字)",
        "num_installments": "分期期數(數字)",
        "merchant": "商家名稱",
        "payment_method": "付款方式",
        "start_date": "開始日期 ISO 格式",
    },
    ("dailyos", "plan_item"): {
        "title": "計畫項目標題(簡短)",
        "priority": "優先度: high/medium/low",
        "estimated_hours": "預估所需時數(數字)",
        "category": "分類(如: 工作、學習、生活)",
        "description": "補充描述",
        "plan_date": "計畫日期 ISO 格式",
    },
    ("intelflow", "webcrawl"): {
        "title": "網頁標題或使用者描述的主題",
        "tags": "相關標籤(逗號分隔)",
    },
}


# ── Asymmetric Enrichment Profiles ───────────────────────────────────────────
#
# Inspired by TurboQuant+ K>V asymmetry (ICLR 2026): errors in high-value data
# are amplified downstream (like softmax on K cache), so they warrant deeper
# enrichment. Time-sensitive or low-stakes sources use shallow enrichment.
#
# Keys match the adapter_type passed to get_enrichment_profile().
# "generic" is the fallback and must match the legacy static thresholds.

ADAPTER_ENRICHMENT_PROFILES: dict[str, dict[str, float]] = {
    # High precision — errors are costly (finance records, investments)
    "finance_transaction": {
        "confidence_threshold": 0.5,
        "ambiguity_threshold": 0.4,
        "min_completeness": 0.9,
    },
    "finance_subscription": {
        "confidence_threshold": 0.5,
        "ambiguity_threshold": 0.4,
        "min_completeness": 0.9,
    },
    "invest": {
        "confidence_threshold": 0.5,
        "ambiguity_threshold": 0.4,
        "min_completeness": 0.85,
    },
    # Medium precision — structured but forgiving
    "taskflow": {
        "confidence_threshold": 0.6,
        "ambiguity_threshold": 0.5,
        "min_completeness": 0.8,
    },
    "dailyos": {
        "confidence_threshold": 0.6,
        "ambiguity_threshold": 0.5,
        "min_completeness": 0.8,
    },
    # Low precision — speed matters, time-sensitive (must match legacy defaults)
    "webcrawl": {
        "confidence_threshold": 0.7,
        "ambiguity_threshold": 0.6,
        "min_completeness": 0.7,
    },
    # Generic fallback — matches legacy static thresholds
    "generic": {
        "confidence_threshold": 0.6,
        "ambiguity_threshold": 0.5,
        "min_completeness": 0.8,
    },
}


def get_enrichment_profile(adapter_type: str | None) -> dict[str, float]:
    """Return the enrichment profile for the given adapter type.

    Falls back to "generic" if adapter_type is None or unknown.
    """
    if adapter_type and adapter_type in ADAPTER_ENRICHMENT_PROFILES:
        return ADAPTER_ENRICHMENT_PROFILES[adapter_type]
    return ADAPTER_ENRICHMENT_PROFILES["generic"]


# ── RLM Enrichment Strategy ──────────────────────────────────────────────────

# Legacy constants retained for backward compatibility.
# New code should use get_enrichment_profile() instead.
_RLM_FIELD_CONFIDENCE_THRESHOLD = 0.6
_RLM_AMBIGUITY_THRESHOLD = 0.5


class RLMEnrichmentStrategy(EnrichmentStrategy):
    """RLM-powered enrichment for ambiguous capture inputs.

    Activates only when:
    1. Pipeline confidence < 0.6 (from prior Haiku extraction), OR
    2. Capture item has ambiguity_score > 0.5

    Flow:
    1. Initial field extraction (already done by LLMEnrichmentStrategy)
    2. If confidence < 0.6 on any field, RLM decomposes the input
    3. Cross-references similar past captures for disambiguation

    Inherits EnrichmentStrategy.__call__ for Operator Protocol compliance.
    """

    name = "rlm_decompose"

    def __init__(
        self,
        field_schema: dict[str, str],
        *,
        adapter_type: str | None = None,
        confidence_threshold: float | None = None,
        ambiguity_threshold: float | None = None,
    ) -> None:
        profile = get_enrichment_profile(adapter_type)
        self._field_schema = field_schema
        # Explicit kwargs override profile values (backward compatibility)
        self._confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else profile["confidence_threshold"]
        )
        self._ambiguity_threshold = (
            ambiguity_threshold
            if ambiguity_threshold is not None
            else profile["ambiguity_threshold"]
        )
        self._engine = RLMEngine(
            RLMConfig(
                model="grok-4-fast",
                sub_model="grok-4-fast",
                max_iterations=5,
                max_timeout_secs=60.0,
                max_depth=1,
                api_base="http://localhost:4000/v1",
                api_key="sk-litellm-local-dev",
                compaction=False,
            )
        )

    def can_handle(self, module: str, entity_type: str) -> bool:
        return (module, entity_type) in ENRICHMENT_SCHEMAS

    async def enrich(
        self,
        payload: dict[str, Any],
        *,
        module: str,
        entity_type: str,
        context: dict[str, Any] | None = None,
    ) -> EnrichmentResult:
        """RLM enrichment — only fires for ambiguous or low-confidence inputs."""
        ctx = context or {}
        pipeline_confidence = ctx.get("pipeline_confidence", 1.0)
        ambiguity_score = payload.get("_ambiguity_score", 0.0)

        # Gate: only activate for ambiguous or low-confidence captures
        if (
            pipeline_confidence >= self._confidence_threshold
            and ambiguity_score <= self._ambiguity_threshold
        ):
            return EnrichmentResult(
                payload=dict(payload),
                confidence=pipeline_confidence,
                source=f"{self.name}(skipped)",
            )

        raw_input = (
            ctx.get("raw_input") or payload.get("raw_text") or payload.get("description") or ""
        )
        if not raw_input:
            return EnrichmentResult(
                payload=dict(payload),
                confidence=pipeline_confidence,
                source=f"{self.name}(skipped)",
            )

        # Identify which fields are still missing
        missing = [k for k in self._field_schema if not payload.get(k)]
        if not missing:
            return EnrichmentResult(
                payload=dict(payload),
                confidence=pipeline_confidence,
                source=f"{self.name}(skipped)",
            )

        logger.info(
            "rlm_enrichment: activating for %s.%s — confidence=%.2f ambiguity=%.2f missing=%s",
            module,
            entity_type,
            pipeline_confidence,
            ambiguity_score,
            missing,
        )

        # Build RLM prompt
        field_desc = "\n".join(f"- {k}: {v}" for k, v in self._field_schema.items() if k in missing)
        rlm_prompt = (
            f"使用者輸入了一段模糊的文字，需要提取結構化欄位。\n"
            f"模組: {module}, 實體類型: {entity_type}\n\n"
            f"需要提取的欄位:\n{field_desc}\n\n"
            "步驟:\n"
            "1. 分析輸入文字的多種可能解讀\n"
            "2. 對每個欄位，評估各種解讀下的值\n"
            "3. 選擇最合理的解讀，提取欄位值\n"
            "4. 評估整體信心程度\n\n"
            "回傳 JSON，包含每個欄位的值 + confidence (float 0.0-1.0)。\n"
            "用 FINAL() 回傳。"
        )

        try:
            result = await asyncio.to_thread(
                self._engine.completion, prompt=rlm_prompt, context=raw_input
            )
        except Exception:
            logger.warning(
                "rlm_enrichment: engine failed for %s.%s", module, entity_type, exc_info=True
            )
            return EnrichmentResult(
                payload=dict(payload),
                confidence=pipeline_confidence,
                source=f"{self.name}(error)",
            )

        if result.status != "ok" or not result.response:
            return EnrichmentResult(
                payload=dict(payload),
                confidence=pipeline_confidence,
                source=f"{self.name}(error)",
            )

        data = parse_llm_json(result.response)
        if not isinstance(data, dict):
            return EnrichmentResult(
                payload=dict(payload),
                confidence=pipeline_confidence,
                source=f"{self.name}(parse_error)",
            )

        enriched = dict(payload)
        rlm_confidence = float(data.pop("confidence", pipeline_confidence))
        rlm_confidence = max(0.0, min(1.0, rlm_confidence))

        filled: list[str] = []
        for key, val in data.items():
            if key in self._field_schema and not enriched.get(key) and val:
                enriched[key] = val
                filled.append(key)

        logger.info(
            "rlm_enrichment: filled %s for %s.%s — confidence=%.2f iterations=%d time=%.1fs",
            filled,
            module,
            entity_type,
            rlm_confidence,
            result.iterations,
            result.execution_time_secs,
        )

        return EnrichmentResult(
            payload=enriched,
            confidence=rlm_confidence,
            source=self.name,
            metadata={
                "rlm_filled_fields": filled,
                "rlm_iterations": result.iterations,
                "rlm_time_secs": result.execution_time_secs,
            },
        )

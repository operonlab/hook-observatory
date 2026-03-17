"""Enrichment strategies for the capture pipeline.

Inspired by Crawl4AI's orthogonal ExtractionStrategy + ChunkingStrategy composition
pattern. Strategies are composed via EnrichmentPipeline, not nested inheritance.
Each strategy slot is independent — pattern matching, defaults, and LLM enrichment
can be swapped or combined freely.

See AD-12 in docs/architecture/architecture-decisions.md.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# ── Core Abstractions ──


class EnrichmentStrategy(ABC):
    """Base class for capture enrichment strategies.

    Each strategy takes a raw capture payload and returns an enriched version.
    Strategies are composable — multiple can run in sequence via EnrichmentPipeline.

    Analogous to Crawl4AI's ExtractionStrategy ABC:
    - ``extract()`` → our ``enrich()``
    - ``input_format`` attribute → our ``can_handle()`` filter
    """

    name: str = "base"

    @abstractmethod
    async def enrich(
        self,
        payload: dict[str, Any],
        *,
        module: str,
        entity_type: str,
        context: dict[str, Any] | None = None,
    ) -> EnrichmentResult:
        """Enrich a capture payload. Returns enriched payload + metadata."""
        ...

    def can_handle(self, module: str, entity_type: str) -> bool:
        """Whether this strategy applies to the given module/entity_type.

        Default: accept all. Override to scope a strategy to specific modules.
        """
        return True


@dataclass
class EnrichmentResult:
    """Result of a single enrichment step."""

    payload: dict[str, Any]
    confidence: float = 1.0  # 0.0-1.0, how confident the enrichment is
    source: str = ""  # which strategy produced this
    metadata: dict[str, Any] = field(default_factory=dict)  # extra diagnostics


# ── Pipeline ──


class EnrichmentPipeline:
    """Compose multiple enrichment strategies in sequence.

    Analogous to Crawl4AI's ``aprocess_html`` pipeline:
    prefetch → scraping → markdown → extraction → assembly.

    Workshop capture pipeline:
    pattern_match → smart_defaults → llm_enrichment (optional, Phase 3)

    Usage::

        pipeline = (
            EnrichmentPipeline()
            .add(PatternMatchStrategy(patterns={"amount": r"(\\d+(?:\\.\\d+)?)元?"}))
            .add(DefaultsStrategy(adapter_defaults={"currency": "TWD"}))
        )
        result = await pipeline.run(payload, module="finance", entity_type="expense")
    """

    def __init__(self, strategies: list[EnrichmentStrategy] | None = None) -> None:
        self._strategies: list[EnrichmentStrategy] = strategies or []

    def add(self, strategy: EnrichmentStrategy) -> EnrichmentPipeline:
        """Append a strategy and return self (fluent API)."""
        self._strategies.append(strategy)
        return self

    async def run(
        self,
        payload: dict[str, Any],
        *,
        module: str,
        entity_type: str,
        context: dict[str, Any] | None = None,
    ) -> EnrichmentResult:
        """Run all applicable strategies in sequence, threading payload forward.

        The running ``min_confidence`` is injected into the context dict as
        ``pipeline_confidence`` so post-processing strategies like
        ``ConfidenceGateStrategy`` can inspect the accumulated confidence.
        """
        current = dict(payload)
        all_metadata: dict[str, Any] = {}
        min_confidence = 1.0
        sources: list[str] = []
        live_context: dict[str, Any] = dict(context) if context else {}

        for strategy in self._strategies:
            if not strategy.can_handle(module, entity_type):
                continue
            live_context["pipeline_confidence"] = min_confidence
            result = await strategy.enrich(
                current,
                module=module,
                entity_type=entity_type,
                context=live_context,
            )
            current = result.payload
            min_confidence = min(min_confidence, result.confidence)
            if result.source:
                sources.append(result.source)
            all_metadata.update(result.metadata)

        return EnrichmentResult(
            payload=current,
            confidence=min_confidence,
            source=" → ".join(sources),
            metadata=all_metadata,
        )


# ── Concrete Strategies ──


class PatternMatchStrategy(EnrichmentStrategy):
    """Enrich via regex/keyword pattern matching on raw text.

    Example: detect "星巴克 拿鐵 150元" and extract
    ``{merchant: "星巴克", item: "拿鐵", amount: "150"}``.

    Analogous to Crawl4AI's ``JsonCssExtractionStrategy`` — deterministic,
    schema-driven, no LLM required.
    """

    name = "pattern_match"

    def __init__(self, patterns: dict[str, str] | None = None) -> None:
        """
        Args:
            patterns: Mapping of field_name → regex pattern string.
                      Use a capturing group to extract a specific part; otherwise
                      the full match is used.
        """
        self._patterns: dict[str, re.Pattern[str]] = {
            k: re.compile(v) for k, v in (patterns or {}).items()
        }

    async def enrich(
        self,
        payload: dict[str, Any],
        *,
        module: str,
        entity_type: str,
        context: dict[str, Any] | None = None,
    ) -> EnrichmentResult:
        enriched = dict(payload)
        raw_text = payload.get("raw_text", "") or payload.get("description", "")
        matched_fields: list[str] = []

        for field_name, pattern in self._patterns.items():
            if enriched.get(field_name):  # never overwrite existing data
                continue
            m = pattern.search(str(raw_text))
            if m:
                enriched[field_name] = m.group(1) if m.groups() else m.group(0)
                matched_fields.append(field_name)

        return EnrichmentResult(
            payload=enriched,
            confidence=0.8 if matched_fields else 1.0,
            source=self.name,
            metadata={"matched_fields": matched_fields},
        )


class DefaultsStrategy(EnrichmentStrategy):
    """Apply smart defaults from adapter config and user preferences.

    Wraps the existing ``BaseCaptureAdapter.smart_defaults()`` logic as a first-class
    strategy, enabling it to participate in pipeline composition alongside other
    enrichment slots (pattern matching, LLM, etc.).

    Priority (lowest → highest): adapter_defaults → user_prefs → existing payload.
    """

    name = "smart_defaults"

    def __init__(
        self,
        adapter_defaults: dict[str, Any] | None = None,
        user_prefs: dict[str, Any] | None = None,
    ) -> None:
        self._defaults = adapter_defaults or {}
        self._user_prefs = user_prefs or {}

    async def enrich(
        self,
        payload: dict[str, Any],
        *,
        module: str,
        entity_type: str,
        context: dict[str, Any] | None = None,
    ) -> EnrichmentResult:
        # Adapter defaults are the lowest-priority base layer
        enriched = {**self._defaults, **payload}

        # User prefs from context override constructor-level prefs (runtime > static)
        prefs = (context or {}).get("user_prefs", self._user_prefs)
        for key, val in prefs.items():
            if not enriched.get(key):
                enriched[key] = val

        return EnrichmentResult(
            payload=enriched,
            confidence=1.0,
            source=self.name,
        )


class LLMEnrichmentStrategy(EnrichmentStrategy):
    """LLM-powered enrichment using Claude Haiku for fuzzy NL input parsing.

    Runs AFTER PatternMatch and Defaults — only fills fields still missing.
    Uses tool_use for reliable structured output.
    """

    name = "llm_haiku"

    def __init__(
        self,
        field_schema: dict[str, str],  # field_name -> description
        *,
        min_completeness: float = 0.8,  # skip LLM if already above this
    ) -> None:
        self._field_schema = field_schema
        self._min_completeness = min_completeness

    async def enrich(
        self,
        payload: dict[str, Any],
        *,
        module: str,
        entity_type: str,
        context: dict[str, Any] | None = None,
    ) -> EnrichmentResult:
        from datetime import date

        # Skip if all tracked fields are already filled
        missing = [k for k in self._field_schema if not payload.get(k)]
        filled_ratio = (len(self._field_schema) - len(missing)) / max(len(self._field_schema), 1)
        if filled_ratio >= self._min_completeness:
            return EnrichmentResult(
                payload=dict(payload), confidence=1.0, source=f"{self.name}(skipped)"
            )

        # Locate raw input text
        ctx = context or {}
        raw_input = (
            ctx.get("raw_input") or payload.get("raw_text") or payload.get("description") or ""
        )
        if not raw_input:
            return EnrichmentResult(
                payload=dict(payload), confidence=1.0, source=f"{self.name}(skipped)"
            )

        # Build tool schema dynamically — only include missing fields
        today = date.today().isoformat()
        properties: dict[str, Any] = {
            k: {"type": "string", "description": self._field_schema[k]} for k in missing
        }
        properties["confidence"] = {
            "type": "number",
            "description": "整體提取信心程度 0.0-1.0",
        }

        tool = {
            "name": "extract_fields",
            "description": "從輸入中提取結構化欄位",
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": ["confidence"],
            },
        }

        system_prompt = (
            "你是結構化資料提取器。從使用者的模糊中文/英文輸入中，提取以下欄位。\n"
            "規則：\n"
            "- 只填能從輸入明確或合理推斷的欄位\n"
            "- 不確定的欄位不要填\n"
            '- 金額請轉為數字（"一千五" → 1500）\n'
            f'- 日期請轉為 ISO 格式（今天是 {today}，"昨天" → 計算實際日期）\n'
            "- confidence 表示整體提取的信心程度"
        )

        # Lazy import to avoid import-time dependency
        from src.shared.llm_haiku import haiku_extract

        result = await haiku_extract(
            user_message=raw_input,
            tool=tool,
            system=system_prompt,
        )

        if result is None:
            return EnrichmentResult(
                payload=dict(payload), confidence=1.0, source=f"{self.name}(skipped)"
            )

        enriched = dict(payload)
        llm_confidence = float(result.pop("confidence", 0.7))

        # Only fill missing fields — never overwrite existing non-empty values
        filled: list[str] = []
        for key, val in result.items():
            if key in self._field_schema and not enriched.get(key) and val:
                enriched[key] = val
                filled.append(key)

        return EnrichmentResult(
            payload=enriched,
            confidence=llm_confidence,
            source=self.name,
            metadata={"llm_filled_fields": filled},
        )


class ConfidenceGateStrategy(EnrichmentStrategy):
    """Post-processing gate that flags low-confidence captures for human review.

    Runs LAST in the pipeline. Inspects the accumulated ``pipeline_confidence``
    from context and, when below the threshold, annotates the payload with
    review markers so CaptureService can set status to ``needs_review``.
    """

    name = "confidence_gate"

    def __init__(self, threshold: float = 0.5) -> None:
        self._threshold = threshold

    async def enrich(
        self,
        payload: dict[str, Any],
        *,
        module: str,
        entity_type: str,
        context: dict[str, Any] | None = None,
    ) -> EnrichmentResult:
        confidence: float = (context or {}).get("pipeline_confidence", 1.0)
        enriched = dict(payload)

        if confidence < self._threshold:
            enriched["_needs_review"] = True
            enriched["_confidence_reason"] = f"Low enrichment confidence: {confidence:.2f}"

        return EnrichmentResult(
            payload=enriched,
            confidence=confidence,
            source=self.name,
            metadata={
                "gate_threshold": self._threshold,
                "gate_passed": confidence >= self._threshold,
            },
        )

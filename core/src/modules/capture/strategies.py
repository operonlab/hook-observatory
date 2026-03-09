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
        """Run all applicable strategies in sequence, threading payload forward."""
        current = dict(payload)
        all_metadata: dict[str, Any] = {}
        min_confidence = 1.0
        sources: list[str] = []

        for strategy in self._strategies:
            if not strategy.can_handle(module, entity_type):
                continue
            result = await strategy.enrich(
                current,
                module=module,
                entity_type=entity_type,
                context=context,
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

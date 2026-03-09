"""Tests for Crawl4AI-inspired pattern ports (AD-12 Phase 1 + Phase 3).

Covers:
- MemoryAdaptiveRunner (core/src/shared/adaptive.py)
- AdapterManifest + registry (capture module)
- EnrichmentPipeline + strategies (capture/strategies.py)
- WebCrawlCaptureAdapter (capture/webcrawl_adapter.py)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure core/src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── MemoryAdaptiveRunner ──


class TestMemoryAdaptiveRunner:
    """Unit tests for the 3-threshold water level concurrency controller."""

    def _make_runner(self, **kwargs):
        from src.shared.adaptive import AdaptiveConfig, MemoryAdaptiveRunner

        config = AdaptiveConfig(**kwargs)
        return MemoryAdaptiveRunner(config)

    @pytest.mark.asyncio
    async def test_basic_batch(self):
        """All items processed, results in order."""
        runner = self._make_runner(max_concurrent=2, task_timeout=10.0)

        async def double(x: int) -> int:
            await asyncio.sleep(0.01)
            return x * 2

        results = await runner.run_batch([1, 2, 3, 4, 5], double)
        assert results == [2, 4, 6, 8, 10]
        stats = runner.stats
        assert stats["completed"] == 5
        assert stats["failed"] == 0

    @pytest.mark.asyncio
    async def test_failed_items_return_exceptions(self):
        """Failed items return Exception, don't crash the batch."""
        runner = self._make_runner(max_concurrent=2, task_timeout=10.0)

        async def maybe_fail(x: int) -> int:
            if x == 3:
                raise ValueError("bad value")
            return x

        results = await runner.run_batch([1, 2, 3, 4], maybe_fail)
        assert results[0] == 1
        assert results[1] == 2
        assert isinstance(results[2], ValueError)
        assert results[3] == 4
        assert runner.stats["failed"] == 1

    @pytest.mark.asyncio
    async def test_timeout_per_task(self):
        """Tasks exceeding timeout are failed."""
        runner = self._make_runner(max_concurrent=2, task_timeout=0.1)

        async def slow(x: int) -> int:
            await asyncio.sleep(10)
            return x

        results = await runner.run_batch([1], slow)
        assert isinstance(results[0], asyncio.TimeoutError)
        assert runner.stats["failed"] == 1

    @pytest.mark.asyncio
    async def test_pressure_event_pauses_dispatch(self):
        """When memory exceeds threshold, new tasks wait until recovery."""
        runner = self._make_runner(
            max_concurrent=4,
            memory_threshold=0.50,  # 50% threshold
            recovery_threshold=0.30,
            check_interval=0.05,
        )

        async def slow_counter(x: int) -> int:
            await asyncio.sleep(0.15)  # give monitor time to run
            return x

        # Patch where psutil is actually used
        with patch("src.shared.adaptive.psutil") as mock_psutil:
            call_idx = 0

            def make_mem():
                nonlocal call_idx
                call_idx += 1
                m = MagicMock()
                # First 3 checks: 80% (above threshold), then 10% (recovery)
                m.percent = 80.0 if call_idx <= 3 else 10.0
                return m

            mock_psutil.virtual_memory = make_mem

            results = await asyncio.wait_for(
                runner.run_batch([1, 2], slow_counter),
                timeout=5.0,
            )
            assert results == [1, 2]
            assert runner.stats["pressure_events"] >= 1


# ── AdapterManifest + Registry ──


class TestAdapterManifest:
    """Tests for the self-describing adapter manifest system."""

    def test_manifest_from_base_adapter(self):
        from src.modules.capture.adapters import AdapterManifest, BaseCaptureAdapter

        class TestAdapter(BaseCaptureAdapter):
            module = "test"
            entity_type = "item"
            default_ttl_days = 14

        m = TestAdapter.manifest()
        assert isinstance(m, AdapterManifest)
        assert m.module == "test"
        assert m.entity_type == "item"
        assert m.permission == "test.write"
        assert m.default_ttl_days == 14

    def test_registry_collects_manifests(self):
        from src.modules.capture.registry import (
            list_manifests,
            reset_registry,
        )

        reset_registry()
        # Trigger discovery
        manifests = list_manifests()
        # Should find at least the known adapters
        modules = {m.module for m in manifests}
        assert "finance" in modules
        assert "taskflow" in modules
        reset_registry()

    def test_get_permissions_from_manifests(self):
        from src.modules.capture.registry import (
            get_permissions,
            reset_registry,
        )

        reset_registry()
        perms = get_permissions()
        assert perms.get("finance") == "finance.write"
        assert perms.get("taskflow") == "taskflow.write"
        reset_registry()


# ── EnrichmentPipeline ──


class TestEnrichmentPipeline:
    """Tests for the composable enrichment strategy layer."""

    @pytest.mark.asyncio
    async def test_pattern_match_strategy(self):
        from src.modules.capture.strategies import PatternMatchStrategy

        strategy = PatternMatchStrategy(patterns={"amount": r"(\d+)元", "merchant": r"^(\S+)\s"})
        result = await strategy.enrich(
            {"raw_text": "星巴克 拿鐵 150元"},
            module="finance",
            entity_type="transaction",
        )
        assert result.payload["amount"] == "150"
        assert result.payload["merchant"] == "星巴克"
        assert result.confidence < 1.0
        assert "amount" in result.metadata["matched_fields"]

    @pytest.mark.asyncio
    async def test_pattern_match_no_overwrite(self):
        """Existing fields are not overwritten."""
        from src.modules.capture.strategies import PatternMatchStrategy

        strategy = PatternMatchStrategy(patterns={"amount": r"(\d+)元"})
        result = await strategy.enrich(
            {"raw_text": "150元", "amount": "200"},
            module="finance",
            entity_type="transaction",
        )
        assert result.payload["amount"] == "200"  # kept original

    @pytest.mark.asyncio
    async def test_defaults_strategy(self):
        from src.modules.capture.strategies import DefaultsStrategy

        strategy = DefaultsStrategy(
            adapter_defaults={"currency": "TWD", "category": "food"},
            user_prefs={"wallet_id": "default-wallet"},
        )
        result = await strategy.enrich(
            {"amount": 150},
            module="finance",
            entity_type="transaction",
        )
        assert result.payload["currency"] == "TWD"
        assert result.payload["wallet_id"] == "default-wallet"
        assert result.payload["amount"] == 150

    @pytest.mark.asyncio
    async def test_defaults_context_overrides_constructor(self):
        """Runtime context user_prefs override constructor prefs."""
        from src.modules.capture.strategies import DefaultsStrategy

        strategy = DefaultsStrategy(user_prefs={"wallet_id": "old"})
        result = await strategy.enrich(
            {},
            module="finance",
            entity_type="transaction",
            context={"user_prefs": {"wallet_id": "new"}},
        )
        assert result.payload["wallet_id"] == "new"

    @pytest.mark.asyncio
    async def test_pipeline_composition(self):
        """Strategies run in sequence, threading payload forward."""
        from src.modules.capture.strategies import (
            DefaultsStrategy,
            EnrichmentPipeline,
            PatternMatchStrategy,
        )

        pipeline = (
            EnrichmentPipeline()
            .add(PatternMatchStrategy(patterns={"amount": r"(\d+)元"}))
            .add(DefaultsStrategy(adapter_defaults={"currency": "TWD"}))
        )

        result = await pipeline.run(
            {"raw_text": "午餐 250元"},
            module="finance",
            entity_type="transaction",
        )
        assert result.payload["amount"] == "250"
        assert result.payload["currency"] == "TWD"
        assert "pattern_match" in result.source
        assert "smart_defaults" in result.source

    @pytest.mark.asyncio
    async def test_pipeline_can_handle_filter(self):
        """Strategies with can_handle=False are skipped."""
        from src.modules.capture.strategies import (
            DefaultsStrategy,
            EnrichmentPipeline,
            EnrichmentResult,
            EnrichmentStrategy,
        )

        class FinanceOnly(EnrichmentStrategy):
            name = "finance_only"

            def can_handle(self, module, entity_type):
                return module == "finance"

            async def enrich(self, payload, *, module, entity_type, context=None):
                return EnrichmentResult(
                    payload={**payload, "finance_enriched": True},
                    source=self.name,
                )

        pipeline = EnrichmentPipeline([FinanceOnly(), DefaultsStrategy()])

        # Finance module → strategy runs
        r1 = await pipeline.run({}, module="finance", entity_type="tx")
        assert r1.payload.get("finance_enriched") is True

        # Other module → strategy skipped
        r2 = await pipeline.run({}, module="taskflow", entity_type="task")
        assert r2.payload.get("finance_enriched") is None


# ── WebCrawl Adapter ──


class TestWebCrawlAdapter:
    """Tests for the webcrawl capture adapter."""

    def _get_adapter(self):
        from src.modules.capture.webcrawl_adapter import ADAPTERS

        return ADAPTERS[0]

    def test_adapter_discoverable(self):
        """Adapter follows naming convention and exports ADAPTERS."""
        from src.modules.capture.webcrawl_adapter import ADAPTERS

        assert len(ADAPTERS) >= 1
        assert ADAPTERS[0].module == "intelflow"
        assert ADAPTERS[0].entity_type == "webcrawl"

    def test_adapter_manifest(self):
        adapter = self._get_adapter()
        m = adapter.manifest()
        assert m.permission == "intelflow.write"
        assert m.default_ttl_days == 7

    def test_smart_defaults_extracts_domain(self):
        adapter = self._get_adapter()
        result = adapter.smart_defaults(
            {"url": "https://docs.crawl4ai.com/api/strategies/"},
            {},
        )
        assert "docs.crawl4ai.com" in result.get("tags", [])

    def test_completeness_url_required(self):
        adapter = self._get_adapter()
        # No URL → low completeness
        score = adapter.compute_completeness({})
        assert score < 0.5
        # With URL → higher
        score_with_url = adapter.compute_completeness({"url": "https://example.com"})
        assert score_with_url >= 0.6

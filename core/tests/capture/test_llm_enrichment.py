"""Tests for LLMEnrichmentStrategy — mock-based, no real API calls."""

from unittest.mock import AsyncMock, patch

import pytest
from src.modules.capture.strategies import (
    DefaultsStrategy,
    EnrichmentPipeline,
    LLMEnrichmentStrategy,
)

# haiku_extract is lazy-imported inside enrich(), so we patch at its source module
_HAIKU_PATCH = "src.shared.llm_haiku.haiku_extract"


@pytest.mark.asyncio
class TestLLMEnrichmentStrategy:
    async def test_skip_when_all_fields_filled(self):
        """LLM should NOT be called when all schema fields already have values."""
        strategy = LLMEnrichmentStrategy(
            field_schema={
                "amount": "金額",
                "description": "描述",
            }
        )
        payload = {"amount": 100, "description": "午餐"}
        result = await strategy.enrich(
            payload,
            module="finance",
            entity_type="transaction",
            context={"raw_input": "午餐 100 元"},
        )
        assert result.payload == payload  # unchanged
        assert result.confidence == 1.0

    @patch(_HAIKU_PATCH, new_callable=AsyncMock)
    async def test_fills_missing_fields(self, mock_haiku):
        """LLM fills fields that are missing from payload."""
        mock_haiku.return_value = {
            "amount": "1500",
            "description": "跟Alex吃飯",
            "confidence": 0.85,
        }
        strategy = LLMEnrichmentStrategy(
            field_schema={
                "amount": "金額",
                "description": "描述",
                "type": "類型",
            }
        )
        payload = {"type": "expense"}  # amount and description missing
        result = await strategy.enrich(
            payload,
            module="finance",
            entity_type="transaction",
            context={"raw_input": "昨天跟 Alex 吃飯花了大概一千五"},
        )
        assert result.payload["amount"] == "1500"
        assert result.payload["description"] == "跟Alex吃飯"
        assert result.payload["type"] == "expense"  # NOT overwritten
        assert result.confidence == 0.85
        assert result.source == "llm_haiku"

    @patch(_HAIKU_PATCH, new_callable=AsyncMock)
    async def test_never_overwrites_existing(self, mock_haiku):
        """LLM response must not overwrite existing non-empty values."""
        mock_haiku.return_value = {
            "amount": "2000",  # different from existing
            "description": "晚餐",
            "confidence": 0.9,
        }
        strategy = LLMEnrichmentStrategy(
            field_schema={
                "amount": "金額",
                "description": "描述",
            }
        )
        payload = {"amount": 1500}  # already has amount
        result = await strategy.enrich(
            payload,
            module="finance",
            entity_type="transaction",
            context={"raw_input": "晚餐花了兩千"},
        )
        assert result.payload["amount"] == 1500  # preserved original
        assert result.payload["description"] == "晚餐"  # filled missing

    @patch(_HAIKU_PATCH, new_callable=AsyncMock)
    async def test_graceful_on_llm_failure(self, mock_haiku):
        """When LLM returns None (failure), return original payload unchanged."""
        mock_haiku.return_value = None
        strategy = LLMEnrichmentStrategy(field_schema={"amount": "金額"})
        payload = {"type": "expense"}
        result = await strategy.enrich(
            payload, module="finance", entity_type="transaction", context={"raw_input": "買東西"}
        )
        assert result.payload == payload
        assert "skipped" in result.source

    async def test_skip_when_no_raw_input(self):
        """If no raw_input in context (and no raw_text/description in payload), skip LLM."""
        strategy = LLMEnrichmentStrategy(field_schema={"amount": "金額"})
        payload = {"type": "expense"}
        result = await strategy.enrich(
            payload, module="finance", entity_type="transaction", context={}
        )
        assert result.payload == payload
        assert "skipped" in result.source

    @patch(_HAIKU_PATCH, new_callable=AsyncMock)
    async def test_full_pipeline_integration(self, mock_haiku):
        """Test LLM strategy works in a full EnrichmentPipeline."""
        mock_haiku.return_value = {
            "amount": "350",
            "description": "計程車",
            "confidence": 0.9,
        }
        pipeline = (
            EnrichmentPipeline()
            .add(DefaultsStrategy(adapter_defaults={"currency": "TWD", "type": "expense"}))
            .add(
                LLMEnrichmentStrategy(
                    field_schema={
                        "amount": "金額",
                        "description": "描述",
                    }
                )
            )
        )
        result = await pipeline.run(
            {},
            module="finance",
            entity_type="transaction",
            context={"raw_input": "剛搭計程車 350"},
        )
        assert result.payload["currency"] == "TWD"  # from defaults
        assert result.payload["amount"] == "350"  # from LLM
        assert result.payload["description"] == "計程車"  # from LLM
        assert "smart_defaults" in result.source
        assert "llm_haiku" in result.source

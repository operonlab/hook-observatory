"""Invest capture adapter — trade."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.invest.schemas import TradeCreate

from .adapters import BaseCaptureAdapter


class TradeCaptureAdapter(BaseCaptureAdapter):
    module = "invest"
    entity_type = "trade"
    default_ttl_days = 30
    enrichment_adapter_type = "invest"

    field_weights = {
        "position_id": 25,
        "type": 20,
        "shares": 20,
        "price": 20,
        "traded_at": 10,
        "currency": 5,
    }

    default_values = {
        "currency": "TWD",
        "fee": 0,
        "tax": 0,
    }

    def smart_defaults(self, payload: dict[str, Any], user_prefs: dict[str, Any]) -> dict[str, Any]:
        result = {**self.default_values, **payload}

        if result.get("currency") is None:
            result["currency"] = "TWD"

        if result.get("fee") is None:
            result["fee"] = 0

        if result.get("tax") is None:
            result["tax"] = 0

        if result.get("traded_at") is None:
            result["traded_at"] = datetime.now(UTC).isoformat()

        return result

    async def promote(
        self,
        payload: dict[str, Any],
        db: AsyncSession,
        space_id: str,
        created_by: str | None,
    ) -> str:
        from src.modules.invest.services import trade_service

        # Coerce Decimal fields
        for field in ("shares", "price", "fee", "tax"):
            if field in payload and payload[field] is not None:
                payload[field] = Decimal(str(payload[field]))

        # Coerce traded_at string → datetime
        if "traded_at" in payload and isinstance(payload["traded_at"], str):
            payload["traded_at"] = datetime.fromisoformat(payload["traded_at"])

        data = TradeCreate(**payload)
        instance = await trade_service.create(db, space_id, data, created_by)
        return instance.id


ADAPTERS: list[BaseCaptureAdapter] = [TradeCaptureAdapter()]

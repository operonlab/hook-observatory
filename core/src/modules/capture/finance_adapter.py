"""Finance capture adapters — transaction, subscription, installment."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finance.schemas import (
    InstallmentPlanCreate,
    SubscriptionCreate,
    TransactionCreate,
)

from .adapters import BaseCaptureAdapter

# Register finance resolvers on import
from .finance_resolvers import register_finance_resolvers
from .strategies import LLMEnrichmentStrategy

register_finance_resolvers()


class TransactionCaptureAdapter(BaseCaptureAdapter):
    module = "finance"
    entity_type = "transaction"
    default_ttl_days = 30

    @property
    def enrichment_strategies(self):
        from .enrichment_config import ENRICHMENT_SCHEMAS

        schema = ENRICHMENT_SCHEMAS.get(("finance", "transaction"))
        return [LLMEnrichmentStrategy(field_schema=schema)] if schema else []

    reference_fields = {
        "wallet_id": "finance.wallet",
        "category_id": "finance.category",
    }

    field_weights = {
        "amount": 25,
        "type": 20,
        "wallet_id": 20,
        "payment_method": 10,
        "category_id": 10,
        "description": 10,
        "transacted_at": 5,
    }

    default_values = {
        "type": "expense",
        "currency": "TWD",
        "status": "completed",
    }

    def smart_defaults(self, payload: dict[str, Any], user_prefs: dict[str, Any]) -> dict[str, Any]:
        result = {**self.default_values, **payload}

        if not result.get("wallet_id") and user_prefs.get("default_wallet_id"):
            result["wallet_id"] = user_prefs["default_wallet_id"]

        if not result.get("transacted_at"):
            result["transacted_at"] = datetime.now(UTC).isoformat()

        # payment_method → wallet_id 反向推斷（存 display name，promote 時 resolve）
        if not result.get("wallet_id") and result.get("payment_method"):
            from .finance_resolvers import _WALLET_TYPE_MAP

            mapped = _WALLET_TYPE_MAP.get(result["payment_method"])
            if mapped:
                result["wallet_id"] = mapped[1]  # display name, e.g. "現金"

        if not result.get("payment_method") and result.get("wallet_id"):
            result["payment_method"] = user_prefs.get("_wallet_payment_method", "credit_card")
        elif not result.get("payment_method"):
            result["payment_method"] = "credit_card"

        return result

    async def promote(
        self,
        payload: dict[str, Any],
        db: AsyncSession,
        space_id: str,
        created_by: str | None,
    ) -> str:
        from src.modules.finance.services import transaction_service

        # Reference fields already resolved by resolve_references() in services.py

        # Coerce types for Pydantic
        if "amount" in payload:
            payload["amount"] = Decimal(str(payload["amount"]))
        if "fee" in payload and payload["fee"] is not None:
            payload["fee"] = Decimal(str(payload["fee"]))
        if "transacted_at" in payload and isinstance(payload["transacted_at"], str):
            payload["transacted_at"] = datetime.fromisoformat(payload["transacted_at"])

        tags = payload.pop("tags", [])
        data = TransactionCreate(**payload, tags=tags)
        instance = await transaction_service.create(db, space_id, data, created_by)
        return instance.id


class SubscriptionCaptureAdapter(BaseCaptureAdapter):
    module = "finance"
    entity_type = "subscription"
    default_ttl_days = 30

    @property
    def enrichment_strategies(self):
        from .enrichment_config import ENRICHMENT_SCHEMAS

        schema = ENRICHMENT_SCHEMAS.get(("finance", "subscription"))
        return [LLMEnrichmentStrategy(field_schema=schema)] if schema else []

    reference_fields = {
        "wallet_id": "finance.wallet",
        "category_id": "finance.category",
    }

    field_weights = {
        "name": 30,
        "amount": 25,
        "billing_cycle": 20,
        "start_date": 10,
        "wallet_id": 10,
        "category_id": 5,
    }

    default_values = {
        "billing_cycle": "monthly",
        "currency": "TWD",
    }

    def smart_defaults(self, payload: dict[str, Any], user_prefs: dict[str, Any]) -> dict[str, Any]:
        result = {**self.default_values, **payload}
        if not result.get("start_date"):
            result["start_date"] = datetime.now(UTC).strftime("%Y-%m-%d")
        if not result.get("wallet_id") and user_prefs.get("default_wallet_id"):
            result["wallet_id"] = user_prefs["default_wallet_id"]
        return result

    async def promote(
        self,
        payload: dict[str, Any],
        db: AsyncSession,
        space_id: str,
        created_by: str | None,
    ) -> str:
        from src.modules.finance.services import subscription_service

        if "amount" in payload:
            payload["amount"] = Decimal(str(payload["amount"]))
        tags = payload.pop("tags", [])
        data = SubscriptionCreate(**payload, tags=tags)
        instance = await subscription_service.create(db, space_id, data, created_by)
        return instance.id


class InstallmentCaptureAdapter(BaseCaptureAdapter):
    module = "finance"
    entity_type = "installment"
    default_ttl_days = 30

    @property
    def enrichment_strategies(self):
        from .enrichment_config import ENRICHMENT_SCHEMAS

        schema = ENRICHMENT_SCHEMAS.get(("finance", "installment"))
        return [LLMEnrichmentStrategy(field_schema=schema)] if schema else []

    reference_fields = {
        "wallet_id": "finance.wallet",
    }

    field_weights = {
        "description": 15,
        "total_amount": 20,
        "num_installments": 15,
        "installment_amount": 10,
        "wallet_id": 15,
        "payment_method": 10,
        "start_date": 10,
        "merchant": 5,
    }

    default_values = {
        "currency": "TWD",
        "payment_method": "credit_card",
    }

    def smart_defaults(self, payload: dict[str, Any], user_prefs: dict[str, Any]) -> dict[str, Any]:
        result = {**self.default_values, **payload}
        if not result.get("start_date"):
            result["start_date"] = datetime.now(UTC).strftime("%Y-%m-%d")
        if not result.get("wallet_id") and user_prefs.get("default_wallet_id"):
            result["wallet_id"] = user_prefs["default_wallet_id"]
        total = result.get("total_amount")
        count = result.get("num_installments")
        if total and count and not result.get("installment_amount"):
            result["installment_amount"] = round(float(total) / int(count), 2)
        return result

    async def promote(
        self,
        payload: dict[str, Any],
        db: AsyncSession,
        space_id: str,
        created_by: str | None,
    ) -> str:
        from src.modules.finance.services import installment_service

        for field in ("total_amount", "installment_amount", "interest_rate"):
            if field in payload and payload[field] is not None:
                payload[field] = Decimal(str(payload[field]))
        tags = payload.pop("tags", [])
        data = InstallmentPlanCreate(**payload, tags=tags)
        instance = await installment_service.create(db, space_id, data, created_by)
        return instance.id


ADAPTERS: list[BaseCaptureAdapter] = [
    TransactionCaptureAdapter(),
    SubscriptionCaptureAdapter(),
    InstallmentCaptureAdapter(),
]

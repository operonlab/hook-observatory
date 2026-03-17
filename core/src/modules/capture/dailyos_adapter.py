"""DailyOS capture adapter — plan items.

Captures vague intentions like "明天記得開會", "想到一件事要做",
and promotes them into DailyPlan items via the service layer.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import _uuid7_hex

from .adapters import BaseCaptureAdapter
from .strategies import LLMEnrichmentStrategy


class PlanItemCaptureAdapter(BaseCaptureAdapter):
    module = "dailyos"
    entity_type = "plan_item"
    default_ttl_days = 7  # shorter TTL — plan items are time-sensitive

    @property
    def enrichment_strategies(self):
        from .enrichment_config import ENRICHMENT_SCHEMAS

        schema = ENRICHMENT_SCHEMAS.get(("dailyos", "plan_item"))
        return [LLMEnrichmentStrategy(field_schema=schema)] if schema else []

    field_weights = {
        "title": 40,
        "plan_date": 15,
        "priority": 15,
        "estimated_hours": 10,
        "category": 10,
        "description": 10,
    }

    default_values = {
        "priority": "medium",
        "status": "pending",
        "source": "capture",
    }

    def smart_defaults(self, payload: dict[str, Any], user_prefs: dict[str, Any]) -> dict[str, Any]:
        result = {**self.default_values, **payload}

        if not result.get("plan_date"):
            result["plan_date"] = date.today().isoformat()

        if not result.get("context"):
            result["context"] = user_prefs.get("default_context", "default")

        return result

    async def promote(
        self,
        payload: dict[str, Any],
        db: AsyncSession,
        space_id: str,
        created_by: str | None,
    ) -> str:
        from src.modules.dailyos.services import daily_plan_service

        # Extract plan-level fields from payload
        plan_date_str = payload.pop("plan_date", None)
        plan_date = (
            date.fromisoformat(plan_date_str)
            if isinstance(plan_date_str, str)
            else plan_date_str or date.today()
        )
        context = payload.pop("context", "default")

        # Build the plan item dict
        item = {
            "id": _uuid7_hex(),
            "title": payload.get("title", ""),
            "source": payload.get("source", "capture"),
            "priority": payload.get("priority", "medium"),
            "status": payload.get("status", "pending"),
            "estimated_hours": payload.get("estimated_hours"),
            "category": payload.get("category"),
            "tags": payload.get("tags", []),
            "description": payload.get("description"),
            "captured_at": datetime.now(UTC).isoformat(),
        }

        # Get or create the plan for the target date
        plan = await daily_plan_service.get_plan_by_date(db, space_id, plan_date, context)

        if plan:
            # Append item to existing plan
            updated_items = list(plan.items) + [item]
            plan.items = updated_items
            await db.flush()
            await db.refresh(plan)
        else:
            # No existing plan — try to create one via service (needs active method)
            try:
                plan = await daily_plan_service.create_plan(
                    db, space_id, plan_date, created_by, context
                )
                plan.items = list(plan.items) + [item]
                await db.flush()
                await db.refresh(plan)
            except Exception:
                # No active method — create minimal plan directly
                from src.modules.dailyos.models import DailyPlan

                plan = DailyPlan(
                    id=_uuid7_hex(),
                    space_id=space_id,
                    created_by=created_by,
                    plan_date=plan_date,
                    context=context,
                    status="planning",
                    items=[item],
                )
                db.add(plan)
                await db.flush()

        return plan.id


ADAPTERS: list[BaseCaptureAdapter] = [
    PlanItemCaptureAdapter(),
]

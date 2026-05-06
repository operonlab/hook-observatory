"""Daily OS P1 service layer — Micro-Strategy Toggles, Task Funnel, Capacity Bar."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.errors import BadRequestError, NotFoundError
from src.shared.models import _uuid7_hex

from .clock import _today
from .models import BacklogItem, CapacityHistory, UserToggle
from .schemas_p1 import (
    ApplyWorkflowTogglesRequest,
    BacklogItemCreate,
    BacklogItemResponse,
    BacklogItemUpdate,
    BatchToggleRequest,
    CapacityBaselineResponse,
    CapacityHistoryResponse,
    CapacityLogRequest,
    FunnelGroupedResponse,
    FunnelStats,
    ToggleCategoryResponse,
    ToggleResponse,
    ToggleUpsert,
)

# ======================== P1a: Toggle Service ========================

_FUNNEL_ORDER: list[str] = ["backburner", "master", "ready", "scheduled"]


class ToggleService:
    """CRUD + batch operations for UserToggle."""

    async def list_toggles(self, db: AsyncSession, space_id: str) -> list[ToggleResponse]:
        stmt = (
            select(UserToggle)
            .where(UserToggle.space_id == space_id, UserToggle.deleted_at.is_(None))
            .order_by(UserToggle.category.nullslast(), UserToggle.toggle_key)
        )
        rows: Sequence[UserToggle] = (await db.execute(stmt)).scalars().all()
        return [ToggleResponse.model_validate(r) for r in rows]

    async def upsert_toggle(
        self,
        db: AsyncSession,
        space_id: str,
        toggle_key: str,
        data: ToggleUpsert,
        user_id: str | None = None,
    ) -> ToggleResponse:
        stmt = select(UserToggle).where(
            UserToggle.space_id == space_id,
            UserToggle.toggle_key == toggle_key,
            UserToggle.deleted_at.is_(None),
        )
        existing: UserToggle | None = (await db.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.enabled = data.enabled
            if data.category is not None:
                existing.category = data.category
            if data.config is not None:
                existing.config = data.config
            existing.source = data.source
            existing.updated_at = datetime.now(UTC)
            return ToggleResponse.model_validate(existing)

        toggle = UserToggle(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            toggle_key=toggle_key,
            enabled=data.enabled,
            category=data.category,
            config=data.config,
            source=data.source,
        )
        db.add(toggle)
        await db.flush()
        return ToggleResponse.model_validate(toggle)

    async def batch_toggle(
        self,
        db: AsyncSession,
        space_id: str,
        data: BatchToggleRequest,
        user_id: str | None = None,
    ) -> list[ToggleResponse]:
        results: list[ToggleResponse] = []
        for item in data.toggles:
            upsert_data = ToggleUpsert(
                enabled=item.enabled,
                category=item.category,
                config=item.config,
                source=data.source,
            )
            result = await self.upsert_toggle(db, space_id, item.toggle_key, upsert_data, user_id)
            results.append(result)
        return results

    async def list_categories(
        self, db: AsyncSession, space_id: str
    ) -> list[ToggleCategoryResponse]:
        stmt = (
            select(UserToggle.category, func.count(UserToggle.id).label("count"))
            .where(UserToggle.space_id == space_id, UserToggle.deleted_at.is_(None))
            .group_by(UserToggle.category)
            .order_by(UserToggle.category.nullslast())
        )
        rows = (await db.execute(stmt)).all()
        return [
            ToggleCategoryResponse(category=row.category or "uncategorized", count=row.count)
            for row in rows
        ]

    async def delete_toggle(self, db: AsyncSession, space_id: str, toggle_key: str) -> None:
        stmt = select(UserToggle).where(
            UserToggle.space_id == space_id,
            UserToggle.toggle_key == toggle_key,
            UserToggle.deleted_at.is_(None),
        )
        toggle: UserToggle | None = (await db.execute(stmt)).scalar_one_or_none()
        if not toggle:
            raise NotFoundError(f"Toggle '{toggle_key}' not found", code="dailyos.toggle_not_found")
        toggle.deleted_at = datetime.now(UTC)

    async def apply_workflow_toggles(
        self,
        db: AsyncSession,
        space_id: str,
        data: ApplyWorkflowTogglesRequest,
        user_id: str | None = None,
    ) -> list[ToggleResponse]:
        if not data.toggle_overrides:
            return []

        results: list[ToggleResponse] = []
        for key, enabled in data.toggle_overrides.items():
            upsert_data = ToggleUpsert(
                enabled=enabled,
                source="workflow",
                config={"workflow_id": data.workflow_id},
            )
            result = await self.upsert_toggle(db, space_id, key, upsert_data, user_id)
            results.append(result)
        return results


# ======================== P1b: Funnel Service ========================


class FunnelService:
    """CRUD + promote/demote for BacklogItem funnel."""

    def _to_response(self, item: BacklogItem) -> BacklogItemResponse:
        return BacklogItemResponse.model_validate(item)

    async def list_grouped(
        self,
        db: AsyncSession,
        space_id: str,
        layer: str | None = None,
    ) -> FunnelGroupedResponse:
        stmt = select(BacklogItem).where(
            BacklogItem.space_id == space_id,
            BacklogItem.deleted_at.is_(None),
        )
        if layer:
            stmt = stmt.where(BacklogItem.funnel_layer == layer)
        stmt = stmt.order_by(BacklogItem.is_frog.desc(), BacklogItem.created_at.asc())
        rows: Sequence[BacklogItem] = (await db.execute(stmt)).scalars().all()

        grouped = FunnelGroupedResponse()
        for item in rows:
            resp = self._to_response(item)
            if item.funnel_layer == "backburner":
                grouped.backburner.append(resp)
            elif item.funnel_layer == "master":
                grouped.master.append(resp)
            elif item.funnel_layer == "ready":
                grouped.ready.append(resp)
            elif item.funnel_layer == "scheduled":
                grouped.scheduled.append(resp)
        grouped.total = len(rows)
        return grouped

    async def create_item(
        self,
        db: AsyncSession,
        space_id: str,
        data: BacklogItemCreate,
        user_id: str | None = None,
    ) -> BacklogItemResponse:
        item = BacklogItem(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            title=data.title,
            funnel_layer=data.funnel_layer,
            priority=data.priority,
            labels=data.labels,
            energy_level=data.energy_level,
            duration_min=data.duration_min,
            cognitive_cost=data.cognitive_cost,
            do_date=data.do_date,
            due_date=data.due_date,
            start_date=data.start_date,
            parent_id=data.parent_id,
            notes=data.notes,
            source_module=data.source_module,
            source_id=data.source_id,
            reward_points=data.reward_points,
            is_frog=data.is_frog,
            extra=data.extra,
        )
        db.add(item)
        await db.flush()
        return self._to_response(item)

    async def get_item(self, db: AsyncSession, item_id: str, space_id: str) -> BacklogItem:
        stmt = select(BacklogItem).where(
            BacklogItem.id == item_id,
            BacklogItem.space_id == space_id,
            BacklogItem.deleted_at.is_(None),
        )
        item: BacklogItem | None = (await db.execute(stmt)).scalar_one_or_none()
        if not item:
            raise NotFoundError("Backlog item not found", code="dailyos.backlog_not_found")
        return item

    async def update_item(
        self,
        db: AsyncSession,
        item_id: str,
        space_id: str,
        data: BacklogItemUpdate,
        user_id: str | None = None,
    ) -> BacklogItemResponse:
        item = await self.get_item(db, item_id, space_id)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(item, field, value)
        item.updated_at = datetime.now(UTC)
        await db.flush()
        return self._to_response(item)

    async def delete_item(self, db: AsyncSession, item_id: str, space_id: str) -> None:
        item = await self.get_item(db, item_id, space_id)
        item.deleted_at = datetime.now(UTC)

    async def promote(self, db: AsyncSession, item_id: str, space_id: str) -> BacklogItemResponse:
        item = await self.get_item(db, item_id, space_id)
        layer = item.funnel_layer
        current_idx = _FUNNEL_ORDER.index(layer) if layer in _FUNNEL_ORDER else -1
        if current_idx == -1:
            raise BadRequestError(
                f"Unknown funnel layer: {item.funnel_layer}",
                code="dailyos.invalid_layer",
            )
        if current_idx >= len(_FUNNEL_ORDER) - 1:
            # Already at scheduled — next stop is daily_plan (caller handles it)
            raise BadRequestError(
                "Item is already at 'scheduled'. Use daily plan to promote further.",
                code="dailyos.already_at_top",
            )
        item.funnel_layer = _FUNNEL_ORDER[current_idx + 1]
        item.updated_at = datetime.now(UTC)
        await db.flush()
        return self._to_response(item)

    async def demote(self, db: AsyncSession, item_id: str, space_id: str) -> BacklogItemResponse:
        item = await self.get_item(db, item_id, space_id)
        layer = item.funnel_layer
        current_idx = _FUNNEL_ORDER.index(layer) if layer in _FUNNEL_ORDER else -1
        if current_idx == -1:
            raise BadRequestError(
                f"Unknown funnel layer: {item.funnel_layer}",
                code="dailyos.invalid_layer",
            )
        if current_idx == 0:
            raise BadRequestError(
                "Item is already at 'backburner'. Cannot demote further.",
                code="dailyos.already_at_bottom",
            )
        item.funnel_layer = _FUNNEL_ORDER[current_idx - 1]
        item.defer_count = (item.defer_count or 0) + 1
        item.updated_at = datetime.now(UTC)
        await db.flush()
        return self._to_response(item)

    async def get_stats(self, db: AsyncSession, space_id: str) -> FunnelStats:
        stmt = (
            select(BacklogItem.funnel_layer, func.count(BacklogItem.id).label("cnt"))
            .where(BacklogItem.space_id == space_id, BacklogItem.deleted_at.is_(None))
            .group_by(BacklogItem.funnel_layer)
        )
        rows = (await db.execute(stmt)).all()
        counts: dict[str, int] = {row.funnel_layer: row.cnt for row in rows}
        return FunnelStats(
            backburner=counts.get("backburner", 0),
            master=counts.get("master", 0),
            ready=counts.get("ready", 0),
            scheduled=counts.get("scheduled", 0),
            total=sum(counts.values()),
        )


# ======================== P1c: Capacity Service ========================


class CapacityService:
    """Log + retrieve capacity history; auto-calculate 14-day baseline."""

    async def log(
        self,
        db: AsyncSession,
        space_id: str,
        data: CapacityLogRequest,
        user_id: str | None = None,
    ) -> CapacityHistoryResponse:
        stmt = select(CapacityHistory).where(
            CapacityHistory.space_id == space_id,
            CapacityHistory.log_date == data.log_date,
            CapacityHistory.budget_type == data.budget_type,
            CapacityHistory.deleted_at.is_(None),
        )
        existing: CapacityHistory | None = (await db.execute(stmt)).scalar_one_or_none()

        if existing:
            existing.planned_value = data.planned_value
            existing.actual_value = data.actual_value
            existing.unit = data.unit
            existing.energy_start = data.energy_start
            existing.energy_end = data.energy_end
            existing.mood = data.mood
            existing.notes = data.notes
            existing.updated_at = datetime.now(UTC)
            await db.flush()
            return CapacityHistoryResponse.model_validate(existing)

        entry = CapacityHistory(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            log_date=data.log_date,
            budget_type=data.budget_type,
            planned_value=data.planned_value,
            actual_value=data.actual_value,
            unit=data.unit,
            energy_start=data.energy_start,
            energy_end=data.energy_end,
            mood=data.mood,
            notes=data.notes,
        )
        db.add(entry)
        await db.flush()
        return CapacityHistoryResponse.model_validate(entry)

    async def get_history(
        self,
        db: AsyncSession,
        space_id: str,
        date_from: date,
        date_to: date,
        budget_type: str | None = None,
    ) -> list[CapacityHistoryResponse]:
        stmt = select(CapacityHistory).where(
            CapacityHistory.space_id == space_id,
            CapacityHistory.log_date >= date_from,
            CapacityHistory.log_date <= date_to,
            CapacityHistory.deleted_at.is_(None),
        )
        if budget_type:
            stmt = stmt.where(CapacityHistory.budget_type == budget_type)
        stmt = stmt.order_by(CapacityHistory.log_date.asc())
        rows: Sequence[CapacityHistory] = (await db.execute(stmt)).scalars().all()
        return [CapacityHistoryResponse.model_validate(r) for r in rows]

    async def get_baseline(
        self,
        db: AsyncSession,
        space_id: str,
        budget_type: str = "time",
        window_days: int = 14,
    ) -> CapacityBaselineResponse:
        from datetime import timedelta

        cutoff = _today(space_id) - timedelta(days=window_days)
        stmt = select(CapacityHistory).where(
            CapacityHistory.space_id == space_id,
            CapacityHistory.budget_type == budget_type,
            CapacityHistory.log_date >= cutoff,
            CapacityHistory.deleted_at.is_(None),
        )
        rows: Sequence[CapacityHistory] = (await db.execute(stmt)).scalars().all()

        if not rows:
            return CapacityBaselineResponse(
                budget_type=budget_type,
                planned_mean=0.0,
                planned_std=0.0,
                actual_mean=0.0,
                actual_std=0.0,
                sample_days=0,
                unit="minutes",
            )

        planned_vals = [r.planned_value for r in rows]
        actual_vals = [r.actual_value for r in rows]
        n = len(rows)

        def _mean(vals: list[float]) -> float:
            return sum(vals) / n

        def _std(vals: list[float], mean: float) -> float:
            if n < 2:
                return 0.0
            variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
            return math.sqrt(variance)

        p_mean = _mean(planned_vals)
        a_mean = _mean(actual_vals)
        unit = rows[0].unit if rows else "minutes"

        return CapacityBaselineResponse(
            budget_type=budget_type,
            planned_mean=round(p_mean, 2),
            planned_std=round(_std(planned_vals, p_mean), 2),
            actual_mean=round(a_mean, 2),
            actual_std=round(_std(actual_vals, a_mean), 2),
            sample_days=n,
            unit=unit,
        )


# ======================== Singletons ========================

toggle_service = ToggleService()
funnel_service = FunnelService()
capacity_service = CapacityService()

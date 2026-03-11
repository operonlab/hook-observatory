"""Daily OS service layer — business logic for methods, selections, and plans."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.events.bus import Event, event_bus
from src.events.types import DailyosEvents
from src.shared.errors import BadRequestError, NotFoundError
from src.shared.models import _uuid7_hex
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService

from .models import DailyPlan, Method, MethodSelection, RecurringItem, TaskGroup
from .schemas import (
    DailyPlanResponse,
    DailyPlanUpdate,
    DimensionConflict,
    MethodCreate,
    MethodResponse,
    MethodSelectionCreate,
    MethodSelectionResponse,
    MethodSelectionUpdate,
    MethodUpdate,
    RecurringItemResponse,
    TaskGroupResponse,
)
from .strategies.base import MethodStrategy

# ======================== Method Service ========================


class MethodService(BaseCRUDService[Method, MethodCreate, MethodUpdate, MethodResponse]):
    model = Method
    audit_module = "dailyos"
    audit_entity_type = "methods"

    def before_create(self, data: MethodCreate, **kwargs: Any) -> dict:
        d = data.model_dump()
        if d.get("is_preset"):
            raise BadRequestError(
                "Cannot create preset methods via API",
                code="dailyos.preset_readonly",
            )
        self._validate_config(d.get("config", {}))
        return d

    def before_update(self, instance: Method, data: MethodUpdate) -> dict:
        if instance.is_preset:
            raise BadRequestError(
                "Cannot modify preset methods. Clone it first.",
                code="dailyos.preset_readonly",
            )
        d = data.model_dump(exclude_unset=True)
        if "config" in d:
            self._validate_config(d["config"])
            d["version"] = instance.version + 1
        return d

    def _validate_config(self, config: dict) -> None:
        """Validate method config structure. Uses lightweight checks."""
        max_items = config.get("max_items")
        if max_items is not None and (not isinstance(max_items, int) or max_items < 1):
            raise BadRequestError(
                "max_items must be a positive integer or null",
                code="dailyos.invalid_config",
            )
        ordering = config.get("ordering", "free")
        if ordering not in ("sequential", "priority", "time", "free", "category"):
            raise BadRequestError(
                f"Invalid ordering: {ordering}",
                code="dailyos.invalid_config",
            )

    def after_create(self, instance: Method) -> None:
        import asyncio

        coro = event_bus.publish(
            Event(
                type=DailyosEvents.METHOD_CREATED,
                data={
                    "method_id": instance.id,
                    "id": instance.id,
                    "space_id": instance.space_id,
                    "name": instance.name,
                    "name_zh": instance.name_zh,
                    "description": instance.description,
                    "tags": instance.tags or [],
                    "created_at": instance.created_at.isoformat() if instance.created_at else None,
                    "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
                },
                source="dailyos",
                user_id=instance.created_by,
            )
        )
        asyncio.ensure_future(coro)  # noqa: RUF006

    def after_update(self, instance: Method, changes: dict) -> None:
        import asyncio

        coro = event_bus.publish(
            Event(
                type=DailyosEvents.METHOD_UPDATED,
                data={
                    "method_id": instance.id,
                    "id": instance.id,
                    "space_id": instance.space_id,
                    "name": instance.name,
                    "name_zh": instance.name_zh,
                    "description": instance.description,
                    "tags": instance.tags or [],
                    "created_at": instance.created_at.isoformat() if instance.created_at else None,
                    "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
                },
                source="dailyos",
                user_id=instance.created_by,
            )
        )
        asyncio.ensure_future(coro)  # noqa: RUF006

    def to_response(self, instance: Method) -> MethodResponse:
        return MethodResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            slug=instance.slug,
            name=instance.name,
            name_zh=instance.name_zh,
            description=instance.description,
            icon=instance.icon,
            color=instance.color,
            is_preset=instance.is_preset,
            cloned_from_id=instance.cloned_from_id,
            config=instance.config,
            version=instance.version,
            layout_type=instance.layout_type,
            tags=instance.tags,
            deleted_at=instance.deleted_at,
        )

    async def list_methods(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
        include_presets: bool = True,
    ) -> PaginatedResponse[MethodResponse]:
        """List methods for a space, optionally including system presets."""
        p = pagination or PaginationParams()
        filters = [Method.deleted_at == None]  # noqa: E711
        if include_presets:
            from sqlalchemy import or_

            filters.append(or_(Method.space_id == space_id, Method.space_id == "system"))
        else:
            filters.append(Method.space_id == space_id)

        count_q = select(func.count()).select_from(Method).where(*filters)
        total = (await db.execute(count_q)).scalar_one()

        q = (
            select(Method)
            .where(*filters)
            .order_by(Method.is_preset.desc(), Method.created_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows: Sequence[Method] = (await db.execute(q)).scalars().all()
        return PaginatedResponse[MethodResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def clone_method(
        self,
        db: AsyncSession,
        method_id: str,
        space_id: str,
        user_id: str | None = None,
    ) -> Method:
        """Clone a method (typically a preset) into the user's space."""
        source = await self.get(db, method_id)
        if not source:
            raise NotFoundError("Method not found", code="dailyos.method_not_found")

        clone = Method(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            slug=f"{source.slug}-custom",
            name=f"{source.name} (Custom)",
            name_zh=f"{source.name_zh} (自訂)" if source.name_zh else None,
            description=source.description,
            icon=source.icon,
            color=source.color,
            is_preset=False,
            cloned_from_id=source.id,
            config=dict(source.config),
            version=1,
            layout_type=source.layout_type,
            tags=list(source.tags) if source.tags else None,
        )
        db.add(clone)
        await db.flush()
        return clone


# ======================== Method Selection Service ========================


class MethodSelectionService(
    BaseCRUDService[
        MethodSelection,
        MethodSelectionCreate,
        MethodSelectionUpdate,
        MethodSelectionResponse,
    ]
):
    model = MethodSelection
    audit_module = "dailyos"
    audit_entity_type = "method_selections"

    def to_response(self, instance: MethodSelection) -> MethodSelectionResponse:
        method_resp: MethodResponse | None = None
        if instance.method:
            method_resp = method_service.to_response(instance.method)

        return MethodSelectionResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            method_id=instance.method_id,
            context=instance.context,
            is_active=instance.is_active,
            overrides=instance.overrides,
            activated_at=instance.activated_at,
            deactivated_at=instance.deactivated_at,
            method=method_resp,
            deleted_at=instance.deleted_at,
        )

    async def get_active(
        self, db: AsyncSession, space_id: str, context: str = "default"
    ) -> list[MethodSelection]:
        """Return all active method selections for a space+context."""
        q = (
            select(MethodSelection)
            .where(
                MethodSelection.space_id == space_id,
                MethodSelection.context == context,
                MethodSelection.is_active == True,  # noqa: E712
                MethodSelection.deleted_at == None,  # noqa: E711
            )
            .order_by(MethodSelection.activated_at.desc())
        )
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    def _get_dimensions(method: Method) -> list[str]:
        """Extract dimension list from method config."""
        return method.config.get("dimensions", [])

    async def activate_method(
        self,
        db: AsyncSession,
        space_id: str,
        method_id: str,
        context: str = "default",
        user_id: str | None = None,
        overrides: dict | None = None,
    ) -> tuple[MethodSelection, list[DimensionConflict]]:
        """Activate a method. All methods can coexist freely (no conflicts)."""
        # Load the target method
        method = await db.get(Method, method_id)
        if not method or method.deleted_at is not None:
            raise NotFoundError("Method not found", code="dailyos.method_not_found")

        # Check if already active
        active = await self.get_active(db, space_id, context)
        for sel in active:
            if sel.method_id == method_id:
                raise BadRequestError(
                    "This method is already active",
                    code="dailyos.already_active",
                )

        # Create new active selection (no dimension conflicts — methods compose freely)
        new_selection = MethodSelection(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            method_id=method_id,
            context=context,
            is_active=True,
            overrides=overrides,
        )
        db.add(new_selection)
        await db.flush()
        await db.refresh(new_selection)
        return new_selection, []

    async def deactivate_method(
        self,
        db: AsyncSession,
        selection_id: str,
    ) -> MethodSelection:
        """Deactivate a specific method selection."""
        sel = await db.get(MethodSelection, selection_id)
        if not sel or sel.deleted_at is not None:
            raise NotFoundError(
                "Method selection not found",
                code="dailyos.selection_not_found",
            )
        if not sel.is_active:
            raise BadRequestError(
                "Method is already inactive",
                code="dailyos.already_inactive",
            )
        sel.is_active = False
        sel.deactivated_at = datetime.now(UTC)
        await db.flush()
        await db.refresh(sel)
        return sel

    async def get_history(
        self,
        db: AsyncSession,
        space_id: str,
        context: str = "default",
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[MethodSelectionResponse]:
        p = pagination or PaginationParams()
        filters = [
            MethodSelection.space_id == space_id,
            MethodSelection.context == context,
            MethodSelection.deleted_at == None,  # noqa: E711
        ]
        count_q = select(func.count()).select_from(MethodSelection).where(*filters)
        total = (await db.execute(count_q)).scalar_one()

        q = (
            select(MethodSelection)
            .where(*filters)
            .order_by(MethodSelection.activated_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows: Sequence[MethodSelection] = (await db.execute(q)).scalars().all()
        return PaginatedResponse[MethodSelectionResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


# ======================== Daily Plan Helpers ========================


def _build_completion_payload(plan) -> dict:
    """Build lean event payload for plan completion."""
    items = plan.items or []
    frog_items = [i for i in items if i.get("is_frog")]
    completed_items = [i for i in items if i.get("status") == "completed"]
    carry_items = [i for i in items if i.get("status") in ("carry", "incomplete")]

    return {
        "plan_id": plan.id,
        "plan_date": str(plan.plan_date),
        "space_id": plan.space_id,
        "completion_score": plan.completion_score,
        "total_items": len(items),
        "completed_count": len(completed_items),
        "carry_count": len(carry_items),
        "frog_completed": any(
            i.get("status") == "completed" for i in frog_items
        ),
        "frog_title": frog_items[0].get("title") if frog_items else None,
        "reflection": plan.reflection,
        "method_state": plan.method_state,
    }


# ======================== Daily Plan Service ========================


class DailyPlanService:
    """Orchestrates plan creation using the active method strategy."""

    @staticmethod
    def _merge_method_configs(selections: list[MethodSelection]) -> dict:
        """Merge configs from all active methods into a composite config.

        The first (most recently activated) method is the primary — its config
        is the base. Subsequent methods contribute additive features only:
        frog, time_awareness, review_cycle, categories, etc.
        """
        if not selections:
            return {}

        primary = selections[0]
        composite = {**primary.method.config, **(primary.overrides or {})}

        for sel in selections[1:]:
            cfg = {**sel.method.config, **(sel.overrides or {})}

            # Merge additive config sections (don't overwrite primary's base)
            if "frog" in cfg and "frog" not in composite:
                composite["frog"] = cfg["frog"]
            if "time_awareness" in cfg and "time_awareness" not in composite:
                composite["time_awareness"] = cfg["time_awareness"]
            if "review_cycle" in cfg:
                composite.setdefault("review_cycle", {})
                for key, val in cfg["review_cycle"].items():
                    if key not in composite["review_cycle"]:
                        composite["review_cycle"][key] = val
            if "categories" in cfg and "categories" not in composite:
                composite["categories"] = cfg["categories"]
            if "completion_rule" in cfg and "completion_rule" not in composite:
                composite["completion_rule"] = cfg["completion_rule"]
            if "overflow" in cfg and "overflow" not in composite:
                composite["overflow"] = cfg["overflow"]
            # Merge ui_hints additively
            if "ui_hints" in cfg:
                composite.setdefault("ui_hints", {})
                for key, val in cfg["ui_hints"].items():
                    if key not in composite["ui_hints"]:
                        composite["ui_hints"][key] = val

        return composite

    async def create_plan(
        self,
        db: AsyncSession,
        space_id: str,
        plan_date: date,
        user_id: str | None = None,
        context: str = "default",
    ) -> DailyPlan:
        """Create a new daily plan using composite config from all active methods."""
        # 1. Get active method selections (multi-active)
        selections = await method_selection_service.get_active(db, space_id, context)
        if not selections:
            raise BadRequestError(
                "No active method configured",
                code="dailyos.no_active_method",
            )

        # Primary selection (most recently activated) — used for plan record link
        selection = selections[0]

        # 2. Merge configs from all active methods
        effective_config = self._merge_method_configs(selections)

        # 3. Instantiate strategy from composite config
        strategy = MethodStrategy.from_config(effective_config)

        # 4. Pull items from source modules (via adapters)
        raw_items = await self._pull_items(db, space_id, effective_config, plan_date)

        # 5. Apply strategy behaviors
        frog_ids = strategy.suggest_frog(raw_items)
        for item in raw_items:
            if item.get("id") in frog_ids:
                item["is_frog"] = True
            if not item.get("category"):
                item["category"] = strategy.assign_category(item)

        sorted_items = strategy.sort_items(raw_items)

        # 6. Validate (return errors as warnings, not blocking)
        _warnings = strategy.validate_plan(sorted_items)

        # 7. Create plan record
        plan = DailyPlan(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            plan_date=plan_date,
            context=context,
            method_selection_id=selection.id,
            status="planning",
            items=sorted_items,
            method_state={"warnings": _warnings} if _warnings else None,
        )
        db.add(plan)
        await db.flush()
        await db.refresh(plan)

        # Publish PLAN_CREATED for Qdrant indexing
        _method_name = selection.method.name if selection.method else None
        await event_bus.publish(
            Event(
                type=DailyosEvents.PLAN_CREATED,
                data={
                    "plan_id": plan.id,
                    "id": plan.id,
                    "space_id": plan.space_id,
                    "reflection": plan.reflection,
                    "tags": [],
                    "method_name": _method_name,
                    "plan_date": str(plan.plan_date),
                    "created_at": plan.created_at.isoformat() if plan.created_at else None,
                    "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
                },
                source="dailyos",
                user_id=user_id,
            )
        )
        return plan

    async def get_or_create_for_date(
        self,
        db: AsyncSession,
        space_id: str,
        plan_date: date,
        user_id: str | None = None,
        context: str = "default",
    ) -> DailyPlan:
        """Get a plan for the given date, or create one if it doesn't exist.

        When creating a new plan, checks the most recent previous plan for
        incomplete items and carries them forward via strategy.handle_overflow().
        """
        # Check for existing plan
        q = select(DailyPlan).where(
            DailyPlan.space_id == space_id,
            DailyPlan.plan_date == plan_date,
            DailyPlan.context == context,
            DailyPlan.deleted_at == None,  # noqa: E711
        )
        existing = (await db.execute(q)).scalar_one_or_none()
        if existing:
            return existing

        # Create plan for the given date
        plan = await self.create_plan(db, space_id, plan_date, user_id, context)

        # Look for the most recent previous plan to carry forward incomplete items
        prev_q = (
            select(DailyPlan)
            .where(
                DailyPlan.space_id == space_id,
                DailyPlan.context == context,
                DailyPlan.plan_date < plan_date,
                DailyPlan.deleted_at == None,  # noqa: E711
            )
            .options(selectinload(DailyPlan.method_selection).selectinload(MethodSelection.method))
            .order_by(DailyPlan.plan_date.desc())
            .limit(1)
        )
        prev_plan = (await db.execute(prev_q)).scalar_one_or_none()

        if prev_plan and prev_plan.items and prev_plan.method_selection:
            method = prev_plan.method_selection.method
            effective_config = {
                **method.config,
                **(prev_plan.method_selection.overrides or {}),
            }
            strategy = MethodStrategy.from_config(effective_config)
            overflow = strategy.handle_overflow(prev_plan.items)
            carry_items = overflow.get("carry", [])
            if carry_items:
                # carry_count already incremented by strategy.handle_overflow()
                # Merge carry items into today's plan (avoiding duplicates)
                existing_ids = {i.get("id") for i in (plan.items or [])}
                merged = list(plan.items or [])
                for item in carry_items:
                    if item.get("id") not in existing_ids:
                        merged.append(item)
                plan.items = merged
                # Store overflow metadata in method_state
                stale_items = overflow.get("stale", [])
                plan.method_state = {
                    **(plan.method_state or {}),
                    "carried_from": prev_plan.plan_date.isoformat(),
                    "carry_count": len(carry_items),
                    "stale_count": len(stale_items),
                }
                await db.flush()
                await db.refresh(plan)

        return plan

    async def get_or_create_today(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None = None,
        context: str = "default",
    ) -> DailyPlan:
        """Convenience wrapper: get or create plan for today."""
        return await self.get_or_create_for_date(db, space_id, date.today(), user_id, context)

    async def get_date_range_stats(
        self,
        db: AsyncSession,
        space_id: str,
        date_from: date,
        date_to: date,
        context: str = "default",
    ) -> list[dict]:
        """Return per-day stats (status, item counts, completion) for a date range."""
        q = (
            select(DailyPlan)
            .where(
                DailyPlan.space_id == space_id,
                DailyPlan.context == context,
                DailyPlan.plan_date >= date_from,
                DailyPlan.plan_date <= date_to,
                DailyPlan.deleted_at == None,  # noqa: E711
            )
            .order_by(DailyPlan.plan_date.asc())
        )
        rows: Sequence[DailyPlan] = (await db.execute(q)).scalars().all()
        stats = []
        for plan in rows:
            items = plan.items or []
            total = len(items)
            done = sum(1 for i in items if i.get("done"))
            stats.append(
                {
                    "plan_date": plan.plan_date.isoformat(),
                    "status": plan.status,
                    "total_items": total,
                    "done_count": done,
                    "completion_score": plan.completion_score or (done / total if total else 0),
                }
            )
        return stats

    async def update_plan(
        self,
        db: AsyncSession,
        plan_id: str,
        data: DailyPlanUpdate,
        user_id: str | None = None,
    ) -> DailyPlan | None:
        """Update a daily plan's items, state, reflection, or score."""
        # Eagerly load method_selection -> method to avoid MissingGreenlet
        stmt = (
            select(DailyPlan)
            .where(DailyPlan.id == plan_id)
            .options(selectinload(DailyPlan.method_selection).selectinload(MethodSelection.method))
        )
        plan = (await db.execute(stmt)).scalar_one_or_none()
        if not plan or plan.deleted_at is not None:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(plan, key, value)

        # Auto-calculate completion score using composite config
        if "items" in update_data and plan.method_selection:
            # Get all active selections for composite config
            active_selections = await method_selection_service.get_active(
                db, plan.space_id, plan.context
            )
            effective_config = (
                self._merge_method_configs(active_selections)
                if active_selections
                else {
                    **plan.method_selection.method.config,
                    **(plan.method_selection.overrides or {}),
                }
            )
            strategy = MethodStrategy.from_config(effective_config)
            is_complete, score = strategy.check_completion(plan.items)
            plan.completion_score = score
            if is_complete and plan.status == "planning":
                plan.status = "completed"
                await event_bus.publish(Event(
                    type=DailyosEvents.PLAN_COMPLETED,
                    data=_build_completion_payload(plan),
                    source="dailyos",
                    user_id=user_id,
                ))

        await db.flush()
        await db.refresh(plan)
        return plan

    async def get_plan(self, db: AsyncSession, plan_id: str) -> DailyPlan | None:
        plan = await db.get(DailyPlan, plan_id)
        if plan and plan.deleted_at is not None:
            return None
        return plan

    async def get_plan_by_date(
        self,
        db: AsyncSession,
        space_id: str,
        plan_date: date,
        context: str = "default",
    ) -> DailyPlan | None:
        q = select(DailyPlan).where(
            DailyPlan.space_id == space_id,
            DailyPlan.plan_date == plan_date,
            DailyPlan.context == context,
            DailyPlan.deleted_at == None,  # noqa: E711
        )
        return (await db.execute(q)).scalar_one_or_none()

    def to_response(self, instance: DailyPlan) -> DailyPlanResponse:
        return DailyPlanResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            plan_date=instance.plan_date,
            context=instance.context,
            method_selection_id=instance.method_selection_id,
            status=instance.status,
            items=instance.items,
            method_state=instance.method_state,
            reflection=instance.reflection,
            completion_score=instance.completion_score,
            deleted_at=instance.deleted_at,
        )

    async def list_plans(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> PaginatedResponse[DailyPlanResponse]:
        """List daily plans for a space with optional date range filter."""
        p = pagination or PaginationParams()
        filters = [
            DailyPlan.space_id == space_id,
            DailyPlan.deleted_at == None,  # noqa: E711
        ]
        if date_from:
            filters.append(DailyPlan.plan_date >= date_from)
        if date_to:
            filters.append(DailyPlan.plan_date <= date_to)

        count_q = select(func.count()).select_from(DailyPlan).where(*filters)
        total = (await db.execute(count_q)).scalar_one()

        q = (
            select(DailyPlan)
            .where(*filters)
            .order_by(DailyPlan.plan_date.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows: Sequence[DailyPlan] = (await db.execute(q)).scalars().all()
        return PaginatedResponse[DailyPlanResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def transition_status(
        self,
        db: AsyncSession,
        plan_id: str,
        new_status: str,
        user_id: str | None = None,
        comment: str | None = None,
    ) -> DailyPlan:
        """Transition a plan's status (planning → active → reviewing → completed)."""
        valid_transitions = {
            "planning": ["active"],
            "active": ["reviewing", "completed"],
            "reviewing": ["completed", "active"],
        }
        plan = await db.get(DailyPlan, plan_id)
        if not plan or plan.deleted_at is not None:
            raise NotFoundError("Plan not found", code="dailyos.plan_not_found")

        allowed = valid_transitions.get(plan.status, [])
        if new_status not in allowed:
            raise BadRequestError(
                f"Cannot transition from '{plan.status}' to '{new_status}'",
                code="dailyos.invalid_transition",
            )
        plan.status = new_status
        if comment and new_status == "completed":
            plan.reflection = comment
        if new_status == "completed":
            await event_bus.publish(Event(
                type=DailyosEvents.PLAN_COMPLETED,
                data=_build_completion_payload(plan),
                source="dailyos",
                user_id=user_id,
            ))
        await db.flush()
        await db.refresh(plan)
        return plan

    async def preview_method(
        self,
        db: AsyncSession,
        method_id: str,
    ) -> dict:
        """Preview what a method would produce as a plan."""
        method = await db.get(Method, method_id)
        if not method or method.deleted_at is not None:
            raise NotFoundError("Method not found", code="dailyos.method_not_found")

        strategy = MethodStrategy.from_config(method.config)
        return {
            "method": method_service.to_response(method),
            "suggested_items": [],
            "frog_ids": [],
            "warnings": strategy.validate_plan([]),
        }

    async def _pull_items(
        self,
        db: AsyncSession,
        space_id: str,
        config: dict,
        plan_date: date,
    ) -> list[dict]:
        """Pull items from enabled source modules."""
        items: list[dict] = []
        sources = config.get("item_sources", {})

        if sources.get("taskflow", {}).get("enabled"):
            # Import lazily to avoid circular dependencies
            try:
                from src.modules.taskflow.services import task_service

                # Pull today's active tasks (excludes done/cancelled)
                today_tasks = await task_service.get_today_tasks(db, space_id)

                # Optionally include overdue tasks
                auto_include_overdue = sources.get("taskflow", {}).get(
                    "auto_include_overdue", False
                )
                overdue_tasks: list = []
                if auto_include_overdue:
                    upcoming = await task_service.get_upcoming_tasks(db, space_id, days=0)
                    # upcoming with days=0 returns tasks with due_date <= now,
                    # which are overdue. Deduplicate against today_tasks.
                    today_ids = {t.id for t in today_tasks}
                    overdue_tasks = [t for t in upcoming if t.id not in today_ids]

                for task_resp in [*today_tasks, *overdue_tasks]:
                    items.append(
                        {
                            "id": task_resp.id,
                            "title": task_resp.title,
                            "source": "taskflow",
                            "priority": task_resp.priority,
                            "status": task_resp.status,
                            "estimated_hours": task_resp.estimated_hours,
                            "due_date": task_resp.due_date.isoformat()
                            if task_resp.due_date
                            else None,
                            "tags": task_resp.tags or [],
                        }
                    )
            except ImportError:
                pass  # taskflow module not available

        # Future: similar adapters for finance, invest, briefing, capture

        return items


# ======================== Guide Generation Service ========================


class GuideService:
    """Generate composite method guides using Codex CLI headless, cached in Redis."""

    CACHE_TTL = 86400 * 7  # 7 days — only regenerate when methods change
    CLI_TIMEOUT = 60  # seconds

    @staticmethod
    def _cache_key(slugs: list[str]) -> str:
        """Generate a stable cache key from sorted method slugs."""
        import hashlib

        sorted_slugs = sorted(slugs)
        slug_hash = hashlib.md5("|".join(sorted_slugs).encode()).hexdigest()[:12]  # noqa: S324
        return f"dailyos:guide:{slug_hash}"

    @staticmethod
    def _build_prompt(methods: list[Method]) -> str:
        """Build the LLM prompt for guide generation."""
        method_descriptions = []
        for m in methods:
            desc = f"- {m.name} ({m.name_zh or ''}): {m.description or ''}"
            cfg = m.config or {}
            if cfg.get("frog", {}).get("enabled"):
                frog_label = cfg["frog"].get("label_zh", "frog")
                desc += f"\n  feature: {frog_label} mechanism"
            if cfg.get("time_awareness", {}).get("enabled"):
                pomo = cfg.get("time_awareness", {}).get("pomodoro")
                if pomo:
                    desc += f"\n  feature: {pomo['work_minutes']}min focus + {pomo['short_break']}min break"  # noqa: E501
            if cfg.get("categories"):
                cats = [c.get("name_zh", c["name"]) for c in cfg["categories"]]
                desc += f"\n  categories: {', '.join(cats)}"
            if cfg.get("review_cycle"):
                reviews = []
                rc = cfg["review_cycle"]
                if rc.get("morning_review", {}).get("enabled"):
                    reviews.append("morning")
                if rc.get("evening_review", {}).get("enabled"):
                    reviews.append("evening")
                if rc.get("weekly_review", {}).get("enabled"):
                    reviews.append("weekly")
                if reviews:
                    desc += f"\n  review: {', '.join(reviews)}"
            method_descriptions.append(desc)

        methods_text = "\n".join(method_descriptions)

        return (
            "\u4f60\u662f\u4e00\u4f4d\u751f\u7522\u529b\u6559\u7df4\u3002"
            "\u4f7f\u7528\u8005\u540c\u6642\u555f\u7528\u4e86\u4ee5\u4e0b\u5e7e\u500b"
            "\u6bcf\u65e5\u898f\u5283\u65b9\u6cd5:\n\n"
            f"{methods_text}\n\n"
            "\u8acb\u7528\u4e00\u6bb5\u81ea\u7136\u6d41\u66a2\u7684\u7e41\u9ad4\u4e2d\u6587"
            "\uff0c\u63cf\u8ff0\u4f7f\u7528\u8005\u4eca\u5929\u5f9e\u65e9\u5230\u665a"
            "\u61c9\u8a72\u600e\u9ebc\u505a\u3002\u8981\u6c42:\n"
            "1. \u7528\u6642\u9593\u6d41\u7a0b\u4e32\u8d77\u4f86"
            "(\u65e9\u4e0a->\u5de5\u4f5c\u6642->\u6536\u5de5)"
            "\uff0c\u4e0d\u8981\u7528\u689d\u5217\u5f0f\n"
            "2. \u628a\u6240\u6709\u65b9\u6cd5\u81ea\u7136\u878d\u5408\u5728\u4e00\u8d77"
            "\uff0c\u50cf\u5728\u8ddf\u670b\u53cb\u89e3\u91cb"
            "\u300c\u6211\u4eca\u5929\u9019\u6a23\u5b89\u6392\u300d\n"
            "3. \u8a9e\u6c23\u8f15\u9b06\u4f46\u6709\u689d\u7406"
            "\uff0c\u50cf\u4e00\u500b\u6709\u7d93\u9a57\u7684\u4eba"
            "\u5728\u5206\u4eab\u81ea\u5df1\u7684\u505a\u6cd5\n"
            "4. 300\u5b57\u4ee5\u5167\n"
            "5. \u6700\u5f8c\u53e6\u8d77\u4e00\u6bb5\uff0c"
            "\u7528\u4e00\u500b\u5177\u9ad4\u7684\u5c0f\u4f8b\u5b50\u8aaa\u660e\n"
            "6. \u4e0d\u8981\u7528\u4efb\u4f55 markdown \u683c\u5f0f\u7b26\u865f"
            "(\u4e0d\u8981 # * - \u7b49)\uff0c\u7d14\u6587\u5b57\u5373\u53ef"
        )

    @staticmethod
    def _codex_env() -> dict[str, str]:
        """Build env for Codex CLI with clean config to avoid MCP loading errors."""
        import os
        import shutil

        codex_home = "/tmp/codex-dailyos"  # noqa: S108
        os.makedirs(codex_home, exist_ok=True)

        # Minimal config (no MCP servers)
        config_path = os.path.join(codex_home, "config.toml")
        if not os.path.exists(config_path):
            with open(config_path, "w") as f:
                f.write('model = "gpt-5.3-codex"\n')

        # Copy auth from default codex home
        auth_src = os.path.expanduser("~/.codex/auth.json")
        auth_dst = os.path.join(codex_home, "auth.json")
        if os.path.exists(auth_src) and not os.path.exists(auth_dst):
            shutil.copy2(auth_src, auth_dst)

        env = os.environ.copy()
        env["CODEX_HOME"] = codex_home
        return env

    async def generate(self, methods: list[Method]) -> str:
        """Generate a composite guide via Codex CLI headless mode.

        Checks Redis cache first; if miss, calls codex exec to generate.
        """
        if not methods:
            return ""

        slugs = [m.slug for m in methods]
        cache_key = self._cache_key(slugs)

        # Check Redis cache
        try:
            from src.shared.redis import get_redis

            redis = get_redis()
            cached = await redis.get(cache_key)
            if cached:
                return cached
        except Exception:  # noqa: S110
            pass

        # Generate via Codex CLI headless mode (codex exec)
        import asyncio

        prompt = self._build_prompt(methods)
        try:
            env = self._codex_env()
            proc = await asyncio.create_subprocess_exec(
                "/opt/homebrew/bin/codex",
                "exec",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=self.CLI_TIMEOUT)
            if proc.returncode != 0:
                return self._fallback_guide(methods)
            guide_text = stdout.decode("utf-8").strip()
            if not guide_text:
                return self._fallback_guide(methods)
        except (TimeoutError, OSError):
            return self._fallback_guide(methods)

        # Cache in Redis
        try:
            from src.shared.redis import get_redis

            redis = get_redis()
            await redis.set(cache_key, guide_text, ex=self.CACHE_TTL)
        except Exception:  # noqa: S110
            pass

        return guide_text

    async def invalidate(self, slugs: list[str]) -> None:
        """Invalidate cached guide for a method combination."""
        cache_key = self._cache_key(slugs)
        try:
            from src.shared.redis import get_redis

            redis = get_redis()
            await redis.delete(cache_key)
        except Exception:  # noqa: S110
            pass

    @staticmethod
    def _fallback_guide(methods: list[Method]) -> str:
        """Simple fallback when CLI is unavailable."""
        names = [m.name_zh or m.name for m in methods]
        joined = "\u3001".join(names)
        return (
            f"\u4f60\u4eca\u5929\u555f\u7528\u4e86\uff1a{joined}\u3002"
            "\u9019\u4e9b\u65b9\u6cd5\u5404\u81ea\u8ca0\u8cac\u4e0d\u540c\u9762\u5411\u2014\u2014"
            "\u6709\u7684\u6c7a\u5b9a\u505a\u4ec0\u9ebc\u3001\u6709\u7684\u6c7a\u5b9a\u600e\u9ebc\u505a\u3001"
            "\u6709\u7684\u5e6b\u4f60\u8ffd\u8e64\u9032\u5ea6\u3001\u6709\u7684\u63d0\u9192\u4f60\u53cd\u601d\u3002"
            "\u5b83\u5011\u4e92\u88dc\u4e0d\u885d\u7a81\uff0c"
            "\u6309\u7167\u5404\u65b9\u6cd5\u7684\u6838\u5fc3\u7cbe\u795e\u53bb\u57f7\u884c\u5c31\u597d\u3002"
        )


# ======================== Recurring Item Service ========================


class RecurringItemService:
    """CRUD + date-based filtering for recurring plan items."""

    async def list_items(self, db: AsyncSession, space_id: str) -> list[RecurringItemResponse]:
        """List all recurring items for a space."""
        q = (
            select(RecurringItem)
            .where(
                RecurringItem.space_id == space_id,
                RecurringItem.deleted_at == None,  # noqa: E711
            )
            .order_by(RecurringItem.created_at.desc())
        )
        rows = (await db.execute(q)).scalars().all()
        return [RecurringItemResponse.model_validate(r) for r in rows]

    async def create_item(
        self, db: AsyncSession, space_id: str, data, user_id: str | None = None
    ) -> RecurringItemResponse:
        """Create a new recurring item."""
        item = RecurringItem(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            **data.model_dump(),
        )
        db.add(item)
        await db.flush()
        await db.refresh(item)
        return RecurringItemResponse.model_validate(item)

    async def update_item(
        self, db: AsyncSession, item_id: str, space_id: str, data
    ) -> RecurringItemResponse:
        """Update a recurring item (verify ownership by space)."""
        item = await db.get(RecurringItem, item_id)
        if not item or item.deleted_at is not None or str(item.space_id) != str(space_id):
            raise NotFoundError("Recurring item not found", code="dailyos.recurring_not_found")

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(item, key, value)

        await db.flush()
        await db.refresh(item)
        return RecurringItemResponse.model_validate(item)

    async def delete_item(self, db: AsyncSession, item_id: str, space_id: str) -> None:
        """Delete a recurring item (verify ownership by space)."""
        item = await db.get(RecurringItem, item_id)
        if not item or item.deleted_at is not None or str(item.space_id) != str(space_id):
            raise NotFoundError("Recurring item not found", code="dailyos.recurring_not_found")

        await db.delete(item)
        await db.flush()

    async def get_items_for_date(
        self, db: AsyncSession, space_id: str, target_date: date
    ) -> list[RecurringItemResponse]:
        """Get recurring items applicable for a specific date."""
        q = select(RecurringItem).where(
            RecurringItem.space_id == space_id,
            RecurringItem.is_active == True,  # noqa: E712
            RecurringItem.deleted_at == None,  # noqa: E711
        )
        rows = (await db.execute(q)).scalars().all()

        result = []
        for item in rows:
            if item.recurrence_type == "daily":
                result.append(item)
            elif item.recurrence_type == "weekly" and item.day_of_week is not None:
                if target_date.weekday() == item.day_of_week:
                    result.append(item)
            elif item.recurrence_type == "monthly" and item.day_of_month is not None:
                if target_date.day == item.day_of_month:
                    result.append(item)

        return [RecurringItemResponse.model_validate(r) for r in result]


class TaskGroupService:
    """CRUD for user-defined task groups."""

    async def list_groups(self, db: AsyncSession, space_id: str) -> list[TaskGroupResponse]:
        q = (
            select(TaskGroup)
            .where(TaskGroup.space_id == space_id, TaskGroup.deleted_at == None)  # noqa: E711
            .order_by(TaskGroup.sort_order.asc(), TaskGroup.created_at.asc())
        )
        rows = (await db.execute(q)).scalars().all()
        return [TaskGroupResponse.model_validate(r) for r in rows]

    async def create_group(
        self, db: AsyncSession, space_id: str, data, user_id: str | None = None
    ) -> TaskGroupResponse:
        group = TaskGroup(
            id=_uuid7_hex(), space_id=space_id, created_by=user_id, **data.model_dump()
        )
        db.add(group)
        await db.flush()
        await db.refresh(group)
        return TaskGroupResponse.model_validate(group)

    async def update_group(
        self, db: AsyncSession, group_id: str, space_id: str, data
    ) -> TaskGroupResponse:
        group = await db.get(TaskGroup, group_id)
        if not group or group.deleted_at is not None or str(group.space_id) != str(space_id):
            raise NotFoundError("Task group not found", code="dailyos.group_not_found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(group, key, value)
        await db.flush()
        await db.refresh(group)
        return TaskGroupResponse.model_validate(group)

    async def delete_group(self, db: AsyncSession, group_id: str, space_id: str) -> None:
        group = await db.get(TaskGroup, group_id)
        if not group or group.deleted_at is not None or str(group.space_id) != str(space_id):
            raise NotFoundError("Task group not found", code="dailyos.group_not_found")
        await db.delete(group)
        await db.flush()


# ======================== Module-level singletons ========================

method_service = MethodService()
method_selection_service = MethodSelectionService()
daily_plan_service = DailyPlanService()
guide_service = GuideService()
recurring_item_service = RecurringItemService()
task_group_service = TaskGroupService()

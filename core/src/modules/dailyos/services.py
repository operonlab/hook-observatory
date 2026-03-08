"""Daily OS service layer — business logic for methods, selections, and plans."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.errors import BadRequestError, NotFoundError
from src.shared.models import _uuid7_hex
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService

from .models import DailyPlan, Method, MethodSelection
from .schemas import (
    DailyPlanResponse,
    DailyPlanUpdate,
    MethodCreate,
    MethodResponse,
    MethodSelectionCreate,
    MethodSelectionResponse,
    MethodUpdate,
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
        MethodUpdate,  # reuse for generic updates
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
    ) -> MethodSelection | None:
        q = select(MethodSelection).where(
            MethodSelection.space_id == space_id,
            MethodSelection.context == context,
            MethodSelection.is_active == True,  # noqa: E712
            MethodSelection.deleted_at == None,  # noqa: E711
        )
        return (await db.execute(q)).scalar_one_or_none()

    async def switch_method(
        self,
        db: AsyncSession,
        space_id: str,
        method_id: str,
        context: str = "default",
        user_id: str | None = None,
        overrides: dict | None = None,
    ) -> MethodSelection:
        """Deactivate current selection and create a new active one."""
        # Deactivate current
        current = await self.get_active(db, space_id, context)
        if current:
            current.is_active = False
            current.deactivated_at = datetime.now(UTC)
            await db.flush()

        # Create new active selection
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
        return new_selection

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


# ======================== Daily Plan Service ========================


class DailyPlanService:
    """Orchestrates plan creation using the active method strategy."""

    async def create_plan(
        self,
        db: AsyncSession,
        space_id: str,
        plan_date: date,
        user_id: str | None = None,
        context: str = "default",
    ) -> DailyPlan:
        """Create a new daily plan using the active method strategy."""
        # 1. Get active method selection
        selection = await method_selection_service.get_active(db, space_id, context)
        if not selection:
            raise BadRequestError(
                "No active method configured",
                code="dailyos.no_active_method",
            )

        # 2. Resolve effective config (method.config merged with overrides)
        method = selection.method
        effective_config = {**method.config, **(selection.overrides or {})}

        # 3. Instantiate strategy
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
        return plan

    async def get_or_create_today(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None = None,
        context: str = "default",
    ) -> DailyPlan:
        """Get today's plan, or create one if it doesn't exist."""
        today = date.today()

        # Check for existing plan
        q = select(DailyPlan).where(
            DailyPlan.space_id == space_id,
            DailyPlan.plan_date == today,
            DailyPlan.context == context,
            DailyPlan.deleted_at == None,  # noqa: E711
        )
        existing = (await db.execute(q)).scalar_one_or_none()
        if existing:
            return existing

        return await self.create_plan(db, space_id, today, user_id, context)

    async def update_plan(
        self,
        db: AsyncSession,
        plan_id: str,
        data: DailyPlanUpdate,
        user_id: str | None = None,
    ) -> DailyPlan | None:
        """Update a daily plan's items, state, reflection, or score."""
        plan = await db.get(DailyPlan, plan_id)
        if not plan or plan.deleted_at is not None:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(plan, key, value)

        # Auto-calculate completion score if items updated
        if "items" in update_data and plan.method_selection:
            method = plan.method_selection.method
            effective_config = {
                **method.config,
                **(plan.method_selection.overrides or {}),
            }
            strategy = MethodStrategy.from_config(effective_config)
            is_complete, score = strategy.check_completion(plan.items)
            plan.completion_score = score
            if is_complete and plan.status == "planning":
                plan.status = "completed"

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

                tasks_response = await task_service.list(
                    db, space_id, PaginationParams(page=1, page_size=100)
                )
                for task_resp in tasks_response.items:
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


# ======================== Module-level singletons ========================

method_service = MethodService()
method_selection_service = MethodSelectionService()
daily_plan_service = DailyPlanService()

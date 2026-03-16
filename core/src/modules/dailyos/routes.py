"""Daily OS routes — REST API endpoints.

Prefix: /api/dailyos (mounted in main.py)
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from .schemas import (
    ActivitySpanCreate,
    ActivitySpanResponse,
    ActivitySpanUpdate,
    DailyOSSearchResult,
    DailyPlanResponse,
    DailyPlanStats,
    DailyPlanUpdate,
    MethodActivateRequest,
    MethodActivateResponse,
    MethodCreate,
    MethodPreviewResponse,
    MethodResponse,
    MethodSelectionResponse,
    MethodUpdate,
    PlanTransitionRequest,
    RecurringItemCreate,
    RecurringItemResponse,
    RecurringItemUpdate,
    TaskGroupCreate,
    TaskGroupResponse,
    TaskGroupUpdate,
)
from .services import (
    activity_span_service,
    daily_plan_service,
    method_selection_service,
    method_service,
    recurring_item_service,
    task_group_service,
)

router = APIRouter(tags=["dailyos"])


# ======================== Search ========================


@router.get("/search", response_model=list[DailyOSSearchResult])
async def search_dailyos(
    q: str = Query(..., description="Search query string"),
    space_id: str = Query("default"),
    entity_type: str | None = Query(None, description="Filter by entity type: 'plan' or 'method'"),
    top_k: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Search Daily OS plans and methods using Qdrant hybrid search with ILIKE fallback."""
    import logging

    from sqlalchemy import or_, select

    from src.shared.qdrant_client import is_available as qdrant_available
    from src.shared.qdrant_search import hybrid_search as qdrant_hybrid_search
    from src.shared.search_types import SearchConfig

    from .models import DailyPlan, Method

    logger = logging.getLogger(__name__)

    # --- Qdrant path ---
    if qdrant_available():
        config = SearchConfig(
            top_k=top_k,
            service_ids=["dailyos"],
        )
        results, _meta = await qdrant_hybrid_search(q, space_id, config)

        if results:
            filtered = [r for r in results if entity_type is None or r.entity_type == entity_type]
            if filtered:
                return [
                    DailyOSSearchResult(
                        entity_type=r.entity_type,
                        entity_id=r.entity_id,
                        score=r.score,
                        content_preview=r.content_preview,
                        metadata=r.metadata,
                    )
                    for r in filtered
                ]

        logger.debug(
            "Qdrant returned 0 results for dailyos space=%s query=%r — falling back to ILIKE",
            space_id,
            q,
        )

    # --- ILIKE fallback ---
    pattern = f"%{q}%"
    output: list[DailyOSSearchResult] = []

    if entity_type is None or entity_type == "plan":
        stmt = (
            select(DailyPlan)
            .where(
                DailyPlan.space_id == space_id,
                DailyPlan.deleted_at.is_(None),
                DailyPlan.reflection.ilike(pattern),
            )
            .order_by(DailyPlan.updated_at.desc())
            .limit(top_k)
        )
        rows = (await db.execute(stmt)).scalars().all()
        for plan in rows:
            output.append(
                DailyOSSearchResult(
                    entity_type="plan",
                    entity_id=plan.id,
                    score=1.0,
                    content_preview=(plan.reflection or "")[:200],
                    metadata={
                        "date": str(plan.plan_date),
                        "score": plan.completion_score,
                    },
                )
            )

    if entity_type is None or entity_type == "method":
        stmt_m = (
            select(Method)
            .where(
                Method.space_id == space_id,
                Method.deleted_at.is_(None),
                or_(
                    Method.name.ilike(pattern),
                    Method.description.ilike(pattern),
                ),
            )
            .order_by(Method.updated_at.desc())
            .limit(top_k)
        )
        rows_m = (await db.execute(stmt_m)).scalars().all()
        for method in rows_m:
            preview = " ".join(filter(None, [method.name, method.description]))[:200]
            output.append(
                DailyOSSearchResult(
                    entity_type="method",
                    entity_id=method.id,
                    score=1.0,
                    content_preview=preview,
                    metadata={
                        "category": method.tags[0] if method.tags else None,
                        "origin": "preset" if method.is_preset else "custom",
                    },
                )
            )

    return output[:top_k]


# ======================== Methods CRUD ========================


@router.get("/methods", response_model=PaginatedResponse[MethodResponse])
async def list_methods(
    space_id: str = Query("default"),
    include_presets: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await method_service.list_methods(
        db, space_id, pagination, include_presets=include_presets
    )


@router.get("/methods/{method_id}", response_model=MethodResponse)
async def get_method(
    method_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    instance = await method_service.get(db, method_id)
    if not instance:
        raise NotFoundError("Method not found", code="dailyos.method_not_found")
    return method_service.to_response(instance)


@router.post("/methods", response_model=MethodResponse, status_code=201)
async def create_method(
    data: MethodCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    instance = await method_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return method_service.to_response(instance)


@router.put("/methods/{method_id}", response_model=MethodResponse)
async def update_method(
    method_id: str,
    data: MethodUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    instance = await method_service.update(db, method_id, data, user_id=user.get("id"))
    if not instance:
        raise NotFoundError("Method not found", code="dailyos.method_not_found")
    await db.commit()
    return method_service.to_response(instance)


@router.delete("/methods/{method_id}", status_code=204)
async def delete_method(
    method_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    if not await method_service.delete(db, method_id, user_id=user.get("id")):
        raise NotFoundError("Method not found", code="dailyos.method_not_found")
    await db.commit()


@router.post("/methods/{method_id}/clone", response_model=MethodResponse, status_code=201)
async def clone_method(
    method_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    instance = await method_service.clone_method(db, method_id, space_id, user_id=user.get("id"))
    await db.commit()
    return method_service.to_response(instance)


# ======================== Active Method Config (Multi-Active) ========================


@router.get("/config/method", response_model=list[MethodSelectionResponse])
async def get_active_methods(
    space_id: str = Query("default"),
    context: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Return all currently active method selections."""
    selections = await method_selection_service.get_active(db, space_id, context)
    return [method_selection_service.to_response(s) for s in selections]


@router.post("/config/method/activate", response_model=MethodActivateResponse)
async def activate_method(
    data: MethodActivateRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Activate a method. All methods compose freely — no conflicts."""
    from .services import guide_service

    selection, replaced = await method_selection_service.activate_method(
        db,
        space_id,
        method_id=data.method_id,
        context=data.context,
        user_id=user.get("id"),
        overrides=data.overrides,
    )
    await db.commit()
    active_selections = await method_selection_service.get_active(db, space_id, data.context)
    active_count = len(active_selections)

    # Invalidate guide cache so it regenerates with new method set
    slugs = [s.method.slug for s in active_selections if s.method]
    await guide_service.invalidate(slugs)
    return MethodActivateResponse(
        selection=method_selection_service.to_response(selection),
        replaced=replaced,
        active_count=active_count,
    )


@router.delete("/config/method/{selection_id}", response_model=MethodSelectionResponse)
async def deactivate_method(
    selection_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Deactivate a specific method selection."""
    from .services import guide_service

    sel = await method_selection_service.deactivate_method(db, selection_id)
    await db.commit()

    # Invalidate guide cache
    remaining = await method_selection_service.get_active(db, sel.space_id, sel.context)
    slugs = [s.method.slug for s in remaining if s.method]
    await guide_service.invalidate(slugs)

    return method_selection_service.to_response(sel)


@router.get("/config/guide")
async def get_composite_guide(
    space_id: str = Query("default"),
    context: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Generate a natural-language composite guide from all active methods."""
    from .services import guide_service

    selections = await method_selection_service.get_active(db, space_id, context)
    methods = [s.method for s in selections if s.method]
    if not methods:
        return {"guide": "", "method_count": 0}
    guide_text = await guide_service.generate(methods)
    return {
        "guide": guide_text,
        "method_count": len(methods),
        "method_names": [m.name_zh or m.name for m in methods],
    }


@router.get("/config/method/history", response_model=PaginatedResponse[MethodSelectionResponse])
async def method_history(
    space_id: str = Query("default"),
    context: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await method_selection_service.get_history(db, space_id, context, pagination)


# ======================== Strategy Preview ========================


@router.post("/methods/{method_id}/preview", response_model=MethodPreviewResponse)
async def preview_method(
    method_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    result = await daily_plan_service.preview_method(db, method_id)
    return MethodPreviewResponse(**result)


# ======================== Daily Plans ========================


@router.get("/plans", response_model=PaginatedResponse[DailyPlanResponse])
async def list_plans(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await daily_plan_service.list_plans(
        db, space_id, pagination, date_from=date_from, date_to=date_to
    )


@router.get("/plans/today", response_model=DailyPlanResponse)
async def get_today_plan(
    space_id: str = Query("default"),
    context: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    plan = await daily_plan_service.get_or_create_today(
        db, space_id, user_id=user.get("id"), context=context
    )
    await db.commit()
    return daily_plan_service.to_response(plan)


@router.get("/plans/for-date/{plan_date}", response_model=DailyPlanResponse)
async def get_plan_for_date(
    plan_date: date,
    space_id: str = Query("default"),
    context: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    plan = await daily_plan_service.get_or_create_for_date(
        db, space_id, plan_date, user_id=user.get("id"), context=context
    )
    await db.commit()
    return daily_plan_service.to_response(plan)


@router.get("/plans/stats", response_model=list[DailyPlanStats])
async def get_plan_stats(
    date_from: date = Query(...),
    date_to: date = Query(...),
    space_id: str = Query("default"),
    context: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    return await daily_plan_service.get_date_range_stats(
        db, space_id, date_from, date_to, context
    )


@router.get("/plans/{plan_id}", response_model=DailyPlanResponse)
async def get_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    plan = await daily_plan_service.get_plan(db, plan_id)
    if not plan:
        raise NotFoundError("Plan not found", code="dailyos.plan_not_found")
    return daily_plan_service.to_response(plan)


@router.put("/plans/{plan_id}", response_model=DailyPlanResponse)
async def update_plan(
    plan_id: str,
    data: DailyPlanUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    plan = await daily_plan_service.update_plan(db, plan_id, data, user_id=user.get("id"))
    if not plan:
        raise NotFoundError("Plan not found", code="dailyos.plan_not_found")
    await db.commit()
    return daily_plan_service.to_response(plan)


@router.post("/plans/{plan_id}/transition", response_model=DailyPlanResponse)
async def transition_plan(
    plan_id: str,
    data: PlanTransitionRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    plan = await daily_plan_service.transition_status(
        db, plan_id, data.status, user_id=user.get("id"), comment=data.comment
    )
    await db.commit()
    return daily_plan_service.to_response(plan)


# ======================== Recurring Items ========================


@router.get("/recurring", response_model=list[RecurringItemResponse])
async def list_recurring_items(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    return await recurring_item_service.list_items(db, space_id)


@router.post("/recurring", response_model=RecurringItemResponse, status_code=201)
async def create_recurring_item(
    data: RecurringItemCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    item = await recurring_item_service.create_item(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return item


@router.put("/recurring/{item_id}", response_model=RecurringItemResponse)
async def update_recurring_item(
    item_id: str,
    data: RecurringItemUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    item = await recurring_item_service.update_item(db, item_id, space_id, data)
    await db.commit()
    return item


@router.delete("/recurring/{item_id}", status_code=204)
async def delete_recurring_item(
    item_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    await recurring_item_service.delete_item(db, item_id, space_id)
    await db.commit()


@router.get("/recurring/for-date/{target_date}", response_model=list[RecurringItemResponse])
async def get_recurring_for_date(
    target_date: date,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    return await recurring_item_service.get_items_for_date(db, space_id, target_date)


# ======================== Task Groups ========================


@router.get("/groups", response_model=list[TaskGroupResponse])
async def list_task_groups(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    return await task_group_service.list_groups(db, space_id)


@router.post("/groups", response_model=TaskGroupResponse, status_code=201)
async def create_task_group(
    data: TaskGroupCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    group = await task_group_service.create_group(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return group


@router.put("/groups/{group_id}", response_model=TaskGroupResponse)
async def update_task_group(
    group_id: str,
    data: TaskGroupUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    group = await task_group_service.update_group(db, group_id, space_id, data)
    await db.commit()
    return group


@router.delete("/groups/{group_id}", status_code=204)
async def delete_task_group(
    group_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    await task_group_service.delete_group(db, group_id, space_id)
    await db.commit()


# ======================== Activity Spans ========================


@router.get("/spans", response_model=list[ActivitySpanResponse])
async def list_activity_spans(
    space_id: str = Query("default"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    return await activity_span_service.list_spans(db, space_id, date_from, date_to)


@router.post("/spans", response_model=ActivitySpanResponse, status_code=201)
async def create_activity_span(
    data: ActivitySpanCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    span = await activity_span_service.create_span(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return span


@router.put("/spans/{span_id}", response_model=ActivitySpanResponse)
async def update_activity_span(
    span_id: str,
    data: ActivitySpanUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    span = await activity_span_service.update_span(db, span_id, space_id, data)
    await db.commit()
    return span


@router.delete("/spans/{span_id}", status_code=204)
async def delete_activity_span(
    span_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    await activity_span_service.delete_span(db, span_id, space_id)
    await db.commit()


@router.get("/spans/for-date/{target_date}", response_model=list[ActivitySpanResponse])
async def get_spans_for_date(
    target_date: date,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    return await activity_span_service.get_spans_for_date(db, space_id, target_date)


@router.get("/spans/for-range", response_model=list[ActivitySpanResponse])
async def get_spans_for_range(
    range_start: date = Query(...),
    range_end: date = Query(...),
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    return await activity_span_service.get_spans_for_range(db, space_id, range_start, range_end)

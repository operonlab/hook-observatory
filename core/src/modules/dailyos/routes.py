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
    DailyPlanResponse,
    DailyPlanUpdate,
    MethodCreate,
    MethodPreviewResponse,
    MethodResponse,
    MethodSelectionResponse,
    MethodSwitchRequest,
    MethodUpdate,
    PlanTransitionRequest,
)
from .services import daily_plan_service, method_selection_service, method_service

router = APIRouter(tags=["dailyos"])


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
    instance = await method_service.clone_method(
        db, method_id, space_id, user_id=user.get("id")
    )
    await db.commit()
    return method_service.to_response(instance)


# ======================== Active Method Config ========================


@router.get("/config/method", response_model=MethodSelectionResponse | None)
async def get_active_method(
    space_id: str = Query("default"),
    context: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    selection = await method_selection_service.get_active(db, space_id, context)
    if not selection:
        return None
    return method_selection_service.to_response(selection)


@router.put("/config/method", response_model=MethodSelectionResponse)
async def switch_method(
    data: MethodSwitchRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    selection = await method_selection_service.switch_method(
        db,
        space_id,
        method_id=data.method_id,
        context=data.context,
        user_id=user.get("id"),
        overrides=data.overrides,
    )
    await db.commit()
    return method_selection_service.to_response(selection)


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
    return await method_selection_service.get_history(
        db, space_id, context, pagination
    )


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

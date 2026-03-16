"""Daily OS P1 routes — Micro-Strategy Toggles, Task Funnel, Capacity Bar.

All endpoints mounted under /api/dailyos via router_p1.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission

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
from .services_p1 import capacity_service, funnel_service, toggle_service

router_p1 = APIRouter(tags=["dailyos-p1"])


# ======================== P1a: Toggles ========================


@router_p1.get("/toggles", response_model=list[ToggleResponse])
async def list_toggles(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """List all toggle overrides for a space."""
    return await toggle_service.list_toggles(db, space_id)


@router_p1.put("/toggles/{key}", response_model=ToggleResponse)
async def upsert_toggle(
    key: str,
    data: ToggleUpsert,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Toggle a feature on/off (upsert by toggle_key)."""
    result = await toggle_service.upsert_toggle(db, space_id, key, data, user_id=user.get("id"))
    await db.commit()
    return result


@router_p1.put("/toggles/batch", response_model=list[ToggleResponse])
async def batch_toggle(
    data: BatchToggleRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Batch toggle multiple keys at once."""
    results = await toggle_service.batch_toggle(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return results


@router_p1.get("/toggles/categories", response_model=list[ToggleCategoryResponse])
async def list_toggle_categories(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """List available toggle categories with counts."""
    return await toggle_service.list_categories(db, space_id)


@router_p1.delete("/toggles/{key}", status_code=204)
async def delete_toggle(
    key: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Remove a toggle override (reverts to default)."""
    await toggle_service.delete_toggle(db, space_id, key)
    await db.commit()


@router_p1.post("/toggles/apply-workflow", response_model=list[ToggleResponse])
async def apply_workflow_toggles(
    data: ApplyWorkflowTogglesRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Apply a workflow's toggle_overrides (source='workflow')."""
    results = await toggle_service.apply_workflow_toggles(
        db, space_id, data, user_id=user.get("id")
    )
    await db.commit()
    return results


# ======================== P1b: Funnel ========================


@router_p1.get("/funnel", response_model=FunnelGroupedResponse)
async def list_funnel(
    space_id: str = Query("default"),
    layer: str | None = Query(None, description="Filter by funnel layer"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """List backlog items grouped by funnel layer."""
    return await funnel_service.list_grouped(db, space_id, layer=layer)


@router_p1.post("/funnel", response_model=BacklogItemResponse, status_code=201)
async def create_funnel_item(
    data: BacklogItemCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Create a new backlog item."""
    item = await funnel_service.create_item(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return item


@router_p1.put("/funnel/{item_id}", response_model=BacklogItemResponse)
async def update_funnel_item(
    item_id: str,
    data: BacklogItemUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Update a backlog item."""
    item = await funnel_service.update_item(
        db, item_id, space_id, data, user_id=user.get("id")
    )
    await db.commit()
    return item


@router_p1.delete("/funnel/{item_id}", status_code=204)
async def delete_funnel_item(
    item_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Soft-delete a backlog item."""
    await funnel_service.delete_item(db, item_id, space_id)
    await db.commit()


@router_p1.post("/funnel/{item_id}/promote", response_model=BacklogItemResponse)
async def promote_funnel_item(
    item_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Promote item to next funnel layer (backburner→master→ready→scheduled)."""
    item = await funnel_service.promote(db, item_id, space_id)
    await db.commit()
    return item


@router_p1.post("/funnel/{item_id}/demote", response_model=BacklogItemResponse)
async def demote_funnel_item(
    item_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Demote item to previous funnel layer (increments defer_count)."""
    item = await funnel_service.demote(db, item_id, space_id)
    await db.commit()
    return item


@router_p1.get("/funnel/stats", response_model=FunnelStats)
async def get_funnel_stats(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Count backlog items per funnel layer."""
    return await funnel_service.get_stats(db, space_id)


# ======================== P1c: Capacity ========================


@router_p1.post("/capacity/log", response_model=CapacityHistoryResponse)
async def log_capacity(
    data: CapacityLogRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Log today's planned/actual capacity values (upsert by date + budget_type)."""
    entry = await capacity_service.log(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return entry


@router_p1.get("/capacity/history", response_model=list[CapacityHistoryResponse])
async def get_capacity_history(
    date_from: date = Query(...),
    date_to: date = Query(...),
    space_id: str = Query("default"),
    budget_type: str | None = Query(None, description="Filter by budget type: time or cognitive"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Get capacity history for a date range."""
    return await capacity_service.get_history(db, space_id, date_from, date_to, budget_type)


@router_p1.get("/capacity/baseline", response_model=CapacityBaselineResponse)
async def get_capacity_baseline(
    space_id: str = Query("default"),
    budget_type: str = Query("time", description="Budget type: time or cognitive"),
    window_days: int = Query(14, ge=7, le=90, description="Lookback window in days"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Auto-calculated capacity baseline from recent history (mean + std)."""
    return await capacity_service.get_baseline(db, space_id, budget_type, window_days)

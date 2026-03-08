"""Lifecycle run routes."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from db import LifecycleRun, get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class LifecycleRunCreate(BaseModel):
    trigger: str = "manual"  # manual | cron | api
    skipped_phases: list[str] = Field(default_factory=list)


class LifecycleRunUpdate(BaseModel):
    status: str | None = None
    completed_at: datetime | None = None
    phases: dict[str, Any] | None = None
    total_skills: int | None = None
    test_passed: int | None = None
    test_partial: int | None = None
    test_failed: int | None = None
    sec_clean: int | None = None
    sec_warned: int | None = None
    sec_blocked: int | None = None
    optimized: int | None = None
    changes_applied: int | None = None
    test_details: list[Any] | dict[str, Any] | None = None
    security_details: list[Any] | dict[str, Any] | None = None
    catalog_snapshot: dict[str, Any] | None = None
    skipped_phases: list[str] | None = None
    errors: dict[str, str] | None = None


class LifecycleRunResponse(BaseModel):
    id: str
    run_id: str
    status: str
    trigger: str
    started_at: datetime
    completed_at: datetime | None
    phases: dict[str, Any]
    total_skills: int
    test_passed: int
    test_partial: int
    test_failed: int
    sec_clean: int
    sec_warned: int
    sec_blocked: int
    optimized: int
    changes_applied: int
    test_details: Any | None
    security_details: Any | None
    catalog_snapshot: Any | None
    skipped_phases: list[str] | Any
    errors: dict[str, str] | Any

    model_config = {"from_attributes": True}


class LifecycleRunListResponse(BaseModel):
    items: list[LifecycleRunResponse]
    total: int
    limit: int
    offset: int


class TrendPoint(BaseModel):
    date: str
    total_skills: int
    pass_rate: float
    sec_clean_rate: float


class LifecycleTrendsResponse(BaseModel):
    points: list[TrendPoint]
    total_runs: int
    avg_pass_rate: float


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/lifecycle/runs", status_code=201)
async def create_run(
    body: LifecycleRunCreate,
    db: AsyncSession = Depends(get_session),
) -> LifecycleRunResponse:
    """Create a new lifecycle pipeline run."""
    from datetime import datetime as dt

    run_id = f"lifecycle-{dt.now().strftime('%Y%m%d-%H%M%S')}"
    run = LifecycleRun(
        run_id=run_id,
        trigger=body.trigger,
        skipped_phases=body.skipped_phases,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return LifecycleRunResponse.model_validate(run)


@router.get("/lifecycle/runs")
async def list_runs(
    status: str | None = Query(None),
    trigger: str | None = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> LifecycleRunListResponse:
    """List lifecycle runs with optional filters."""
    query = select(LifecycleRun).order_by(LifecycleRun.started_at.desc())
    count_query = select(func.count()).select_from(LifecycleRun)

    if status:
        query = query.where(LifecycleRun.status == status)
        count_query = count_query.where(LifecycleRun.status == status)
    if trigger:
        query = query.where(LifecycleRun.trigger == trigger)
        count_query = count_query.where(LifecycleRun.trigger == trigger)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(query.offset(offset).limit(limit))
    items = [LifecycleRunResponse.model_validate(r) for r in result.scalars().all()]

    return LifecycleRunListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/lifecycle/runs/{run_id}")
async def get_run(
    run_id: str,
    db: AsyncSession = Depends(get_session),
) -> LifecycleRunResponse:
    """Get a lifecycle run by run_id."""
    result = await db.execute(select(LifecycleRun).where(LifecycleRun.run_id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return LifecycleRunResponse.model_validate(run)


@router.patch("/lifecycle/runs/{run_id}")
async def update_run(
    run_id: str,
    body: LifecycleRunUpdate,
    db: AsyncSession = Depends(get_session),
) -> LifecycleRunResponse:
    """Update a lifecycle run (add phase results, change status)."""
    result = await db.execute(select(LifecycleRun).where(LifecycleRun.run_id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    update_data = body.model_dump(exclude_none=True)

    # Merge phases dict instead of replacing
    if "phases" in update_data and run.phases:
        merged = dict(run.phases)
        merged.update(update_data["phases"])
        update_data["phases"] = merged

    for key, value in update_data.items():
        setattr(run, key, value)

    await db.commit()
    await db.refresh(run)
    return LifecycleRunResponse.model_validate(run)


@router.get("/lifecycle/trends")
async def get_trends(
    days: int = Query(30, le=90),
    db: AsyncSession = Depends(get_session),
) -> LifecycleTrendsResponse:
    """Get lifecycle trend data over time."""
    cutoff = datetime.now() - timedelta(days=days)

    result = await db.execute(
        select(LifecycleRun)
        .where(LifecycleRun.started_at >= cutoff)
        .where(LifecycleRun.status == "completed")
        .order_by(LifecycleRun.started_at.asc())
    )
    runs = result.scalars().all()

    points = []
    for run in runs:
        total = run.total_skills or 1
        pass_rate = ((run.test_passed or 0) / total) * 100 if total > 0 else 0
        sec_rate = ((run.sec_clean or 0) / total) * 100 if total > 0 else 0
        points.append(
            TrendPoint(
                date=run.started_at.strftime("%Y-%m-%d") if run.started_at else "",
                total_skills=run.total_skills or 0,
                pass_rate=round(pass_rate, 1),
                sec_clean_rate=round(sec_rate, 1),
            )
        )

    avg_pass = sum(p.pass_rate for p in points) / len(points) if points else 0

    return LifecycleTrendsResponse(
        points=points,
        total_runs=len(runs),
        avg_pass_rate=round(avg_pass, 1),
    )

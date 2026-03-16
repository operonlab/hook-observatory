"""Aggregated statistics routes."""

from __future__ import annotations

from datetime import datetime

from db import Intent, Invocation, get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from services.telemetry import TelemetryService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TopSkillStat(BaseModel):
    skill_name: str
    count: int
    success_rate: float


class TrendBucket(BaseModel):
    day: str
    count: int


class GlobalStatsResponse(BaseModel):
    total_invocations: int
    total_skills: int
    avg_success_rate: float
    top_skills: list[TopSkillStat]
    trend_7d: list[TrendBucket]


class DailyCount(BaseModel):
    day: str
    count: int


class CommonError(BaseModel):
    error_message: str
    count: int


class SkillStatsResponse(BaseModel):
    skill_name: str
    total_invocations: int
    avg_duration_ms: float | None
    failure_rate: float
    daily_counts: list[DailyCount]
    common_errors: list[CommonError]


class DemandStat(BaseModel):
    skill_name: str
    intents: int
    executions: int
    conversion_rate: float  # executions / intents * 100


class DemandStatsResponse(BaseModel):
    items: list[DemandStat]
    total_intents: int
    total_executions: int
    overall_conversion_rate: float


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/stats")
async def global_stats(
    category: str = Query("skill", description="Category filter; use 'all' for no filter"),
    db: AsyncSession = Depends(get_session),
) -> GlobalStatsResponse:
    """Aggregated stats: top skills by count, avg success rate, 7d trend."""
    svc = TelemetryService(db)
    data = await svc.get_global_stats(category=category)
    return GlobalStatsResponse(**data)


@router.get("/stats/demand")
async def demand_stats(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_session),
) -> DemandStatsResponse:
    """Demand analysis: intents vs executions with conversion rates."""
    intent_query = select(
        Intent.skill_name,
        func.count().label("intent_count"),
    ).group_by(Intent.skill_name)

    exec_query = select(
        Invocation.skill_name,
        func.count().label("exec_count"),
    ).group_by(Invocation.skill_name)

    if since:
        intent_query = intent_query.where(Intent.timestamp >= since)
        exec_query = exec_query.where(Invocation.timestamp >= since)
    if until:
        intent_query = intent_query.where(Intent.timestamp <= until)
        exec_query = exec_query.where(Invocation.timestamp <= until)

    intent_result = await db.execute(intent_query)
    exec_result = await db.execute(exec_query)

    intents = {r.skill_name: r.intent_count for r in intent_result.all()}
    execs = {r.skill_name: r.exec_count for r in exec_result.all()}

    all_skills = set(intents) | set(execs)
    items = []
    for skill in all_skills:
        i = intents.get(skill, 0)
        e = execs.get(skill, 0)
        rate = round(e / i * 100, 1) if i > 0 else 0.0
        items.append(
            DemandStat(
                skill_name=skill,
                intents=i,
                executions=e,
                conversion_rate=rate,
            )
        )

    items.sort(key=lambda x: -(x.intents + x.executions))
    items = items[:limit]

    total_i = sum(intents.values())
    total_e = sum(execs.values())
    overall = round(total_e / total_i * 100, 1) if total_i > 0 else 0.0

    return DemandStatsResponse(
        items=items,
        total_intents=total_i,
        total_executions=total_e,
        overall_conversion_rate=overall,
    )


@router.get("/stats/{name}")
async def skill_stats(
    name: str,
    category: str = Query("skill", description="Category filter; use 'all' for no filter"),
    db: AsyncSession = Depends(get_session),
) -> SkillStatsResponse:
    """Per-skill stats: daily counts, avg duration, failure rate, common errors."""
    svc = TelemetryService(db)
    data = await svc.get_skill_stats(name, category=category)
    if data is None:
        raise HTTPException(status_code=404, detail=f"No invocations found for skill '{name}'")
    return SkillStatsResponse(**data)

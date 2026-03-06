"""Evaluation routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from db import EvalDefinition, Evaluation, get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class EvalTriggerRequest(BaseModel):
    """Request body to trigger a new evaluation."""

    version: str | None = None
    test_cases: list[dict[str, Any]] = Field(default_factory=list)


class EvalUpdateRequest(BaseModel):
    """Request body to update evaluation results."""

    grading_results: list[dict[str, Any]] | None = None
    comparator_results: dict[str, Any] | None = None
    analyzer_report: dict[str, Any] | None = None
    benchmark_score: float | None = None
    benchmark_json: dict[str, Any] | None = None
    status: str | None = None


class EvalDefinitionResponse(BaseModel):
    id: str
    skill_name: str
    test_cases: list[dict[str, Any]] | dict[str, Any]
    version: str | None
    last_run: datetime | None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class EvaluationResponse(BaseModel):
    id: str
    skill_name: str
    version: str | None
    run_timestamp: datetime
    grading_results: list[dict[str, Any]] | dict[str, Any] | None
    comparator_results: dict[str, Any] | None
    analyzer_report: dict[str, Any] | None
    benchmark_score: float | None
    benchmark_json: dict[str, Any] | None
    eval_definition_id: str | None
    status: str

    model_config = {"from_attributes": True}


class EvaluationListResponse(BaseModel):
    items: list[EvaluationResponse]
    total: int
    limit: int
    offset: int


class BenchmarkResponse(BaseModel):
    skill_name: str
    benchmarks: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/evaluations/{name}", status_code=201)
async def trigger_evaluation(
    name: str,
    body: EvalTriggerRequest,
    db: AsyncSession = Depends(get_session),
) -> EvaluationResponse:
    """Trigger a new evaluation for a skill. Stores eval definition and creates a running eval."""
    # Upsert eval definition if test_cases provided
    eval_def_id: str | None = None
    if body.test_cases:
        existing = await db.execute(select(EvalDefinition).where(EvalDefinition.skill_name == name))
        eval_def = existing.scalar_one_or_none()
        if eval_def:
            eval_def.test_cases = body.test_cases
            eval_def.version = body.version
            eval_def.last_run = func.now()
            await db.flush()
            eval_def_id = eval_def.id
        else:
            eval_def = EvalDefinition(
                skill_name=name,
                test_cases=body.test_cases,
                version=body.version,
                last_run=func.now(),
            )
            db.add(eval_def)
            await db.flush()
            await db.refresh(eval_def)
            eval_def_id = eval_def.id
    else:
        # Check for existing definition
        existing = await db.execute(select(EvalDefinition).where(EvalDefinition.skill_name == name))
        eval_def = existing.scalar_one_or_none()
        if eval_def:
            eval_def.last_run = func.now()
            eval_def_id = eval_def.id

    # Create evaluation record in "running" state
    evaluation = Evaluation(
        skill_name=name,
        version=body.version,
        eval_definition_id=eval_def_id,
        status="running",
    )
    db.add(evaluation)
    await db.commit()
    await db.refresh(evaluation)
    return EvaluationResponse.model_validate(evaluation)


@router.get("/evaluations")
async def list_evaluations(
    skill_name: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> EvaluationListResponse:
    """List evaluations with filters."""
    query = select(Evaluation).order_by(Evaluation.run_timestamp.desc())
    count_query = select(func.count()).select_from(Evaluation)

    if skill_name:
        query = query.where(Evaluation.skill_name == skill_name)
        count_query = count_query.where(Evaluation.skill_name == skill_name)
    if status:
        query = query.where(Evaluation.status == status)
        count_query = count_query.where(Evaluation.status == status)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(query.offset(offset).limit(limit))
    items = [EvaluationResponse.model_validate(e) for e in result.scalars().all()]

    return EvaluationListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/evaluations/{name}")
async def get_latest_evaluation(
    name: str,
    db: AsyncSession = Depends(get_session),
) -> EvaluationResponse:
    """Get the latest evaluation for a skill."""
    result = await db.execute(
        select(Evaluation)
        .where(Evaluation.skill_name == name)
        .order_by(Evaluation.run_timestamp.desc())
        .limit(1)
    )
    evaluation = result.scalar_one_or_none()
    if evaluation is None:
        raise HTTPException(status_code=404, detail=f"No evaluations found for skill '{name}'")
    return EvaluationResponse.model_validate(evaluation)


@router.put("/evaluations/{eval_id}")
async def update_evaluation(
    eval_id: str,
    body: EvalUpdateRequest,
    db: AsyncSession = Depends(get_session),
) -> EvaluationResponse:
    """Update evaluation results (grading, comparator, analyzer, benchmark)."""
    result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if evaluation is None:
        raise HTTPException(status_code=404, detail=f"Evaluation '{eval_id}' not found")

    update_data = body.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(evaluation, key, value)

    await db.commit()
    await db.refresh(evaluation)
    return EvaluationResponse.model_validate(evaluation)


@router.get("/evaluations/{name}/benchmark")
async def get_benchmark(
    name: str,
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_session),
) -> BenchmarkResponse:
    """Get benchmark data for a skill across evaluations."""
    result = await db.execute(
        select(Evaluation)
        .where(Evaluation.skill_name == name)
        .where(Evaluation.benchmark_score.is_not(None))
        .order_by(Evaluation.run_timestamp.desc())
        .limit(limit)
    )
    evaluations = result.scalars().all()

    benchmarks = [
        {
            "eval_id": e.id,
            "version": e.version,
            "run_timestamp": e.run_timestamp.isoformat() if e.run_timestamp else None,
            "benchmark_score": e.benchmark_score,
            "benchmark_json": e.benchmark_json,
        }
        for e in evaluations
    ]

    return BenchmarkResponse(skill_name=name, benchmarks=benchmarks)

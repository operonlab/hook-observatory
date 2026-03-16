"""Daily OS P3+P4 routes — Eisenhower, Wizard, Templates, Gamification, Onboarding, Experiments.

Prefix: /api/dailyos (mounted alongside main router in __init__.py)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from .schemas_p3 import (
    AwardPointsRequest,
    AwardPointsResponse,
    EisenhowerResponse,
    ExperimentCreate,
    ExperimentResponse,
    ExperimentResultsResponse,
    ExperimentUpdate,
    GamificationStateResponse,
    InterventionsResponse,
    OnboardingResult,
    OnboardingSubmitRequest,
    PlanTemplateCreate,
    PlanTemplateResponse,
    PlanTemplateUpdate,
    PointHistoryResponse,
    QuizResponse,
    StreakResponse,
    TemplateApplyRequest,
    TemplateApplyResponse,
    WizardRespondRequest,
    WizardStartRequest,
    WizardStepResponse,
)
from .services_p3 import (
    eisenhower_service,
    experiment_service,
    gamification_service,
    onboarding_service,
    template_service,
    wizard_service,
)

router_p3 = APIRouter(tags=["dailyos-p3"])


# ======================== P3a: Eisenhower ========================


@router_p3.get("/eisenhower", response_model=EisenhowerResponse)
async def get_eisenhower(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Return Eisenhower matrix — 4 quadrants populated from backlog items."""
    return await eisenhower_service.get_quadrants(db, space_id)


# ======================== P3b: Procrastination Wizard ========================


@router_p3.post("/wizard/start", response_model=WizardStepResponse)
async def wizard_start(
    data: WizardStartRequest,
    user: dict = require_permission("dailyos.write"),
):
    """Start the procrastination wizard for a specific backlog item."""
    return wizard_service.start(data.item_id)


@router_p3.post("/wizard/respond", response_model=WizardStepResponse)
async def wizard_respond(
    data: WizardRespondRequest,
    user: dict = require_permission("dailyos.write"),
):
    """Submit an answer to the current wizard step; receive next question or final result."""
    return wizard_service.respond(
        item_id=data.item_id,
        step=data.step,
        answer=data.answer,
        session_state=data.session_state,
    )


@router_p3.get("/wizard/interventions", response_model=InterventionsResponse)
async def wizard_interventions(
    user: dict = require_permission("dailyos.read"),
):
    """List available procrastination intervention types."""
    return wizard_service.get_interventions()


# ======================== P3c: Plan Templates ========================


@router_p3.get("/templates", response_model=PaginatedResponse[PlanTemplateResponse])
async def list_templates(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await template_service.list_templates(db, space_id, pagination)


@router_p3.post("/templates", response_model=PlanTemplateResponse, status_code=201)
async def create_template(
    data: PlanTemplateCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    instance = await template_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return template_service.to_response(instance)


@router_p3.post(
    "/templates/from-plan/{plan_id}", response_model=PlanTemplateResponse, status_code=201
)
async def create_template_from_plan(
    plan_id: str,
    data: PlanTemplateCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Create a reusable template from an existing daily plan."""
    instance = await template_service.create_from_plan(
        db,
        plan_id=plan_id,
        space_id=space_id,
        slug=data.slug,
        name=data.name,
        name_zh=data.name_zh,
        description=data.description,
        tags=data.tags,
        user_id=user.get("id"),
    )
    await db.commit()
    return template_service.to_response(instance)


@router_p3.put("/templates/{template_id}", response_model=PlanTemplateResponse)
async def update_template(
    template_id: str,
    data: PlanTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    instance = await template_service.update(db, template_id, data, user_id=user.get("id"))
    if not instance:
        raise NotFoundError("Template not found", code="dailyos.template_not_found")
    await db.commit()
    return template_service.to_response(instance)


@router_p3.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    if not await template_service.delete(db, template_id, user_id=user.get("id")):
        raise NotFoundError("Template not found", code="dailyos.template_not_found")
    await db.commit()


@router_p3.post("/templates/{template_id}/apply", response_model=TemplateApplyResponse)
async def apply_template(
    template_id: str,
    data: TemplateApplyRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Apply a template to today's (or specified date's) daily plan."""
    result = await template_service.apply_template(
        db,
        template_id=template_id,
        space_id=data.space_id,
        plan_date=data.plan_date,
        context=data.context,
        merge_mode=data.merge_mode,
        user_id=user.get("id"),
    )
    await db.commit()
    return result


# ======================== P3d: Gamification ========================


@router_p3.get("/gamification/state", response_model=GamificationStateResponse)
async def get_gamification_state(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Get current gamification state — points, streak, level, achievements."""
    return await gamification_service.get_state(db, space_id)


@router_p3.post("/gamification/award", response_model=AwardPointsResponse)
async def award_points(
    data: AwardPointsRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Award points for an action and update gamification state."""
    result = await gamification_service.award_points(
        db,
        space_id=data.space_id,
        points=data.points,
        reason=data.reason,
        source_type=data.source_type,
        source_id=data.source_id,
        multiplier=data.multiplier,
        user_id=user.get("id"),
    )
    await db.commit()
    return result


@router_p3.get("/gamification/history", response_model=PaginatedResponse[PointHistoryResponse])
async def get_point_history(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Get paginated point history."""
    pagination = PaginationParams(page=page, page_size=page_size)
    return await gamification_service.get_history(db, space_id, pagination)


@router_p3.get("/gamification/streak", response_model=StreakResponse)
async def get_streak(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Get current streak information."""
    return await gamification_service.get_streak(db, space_id)


# ======================== P3e: Onboarding Quiz ========================


@router_p3.get("/onboarding/quiz", response_model=QuizResponse)
async def get_onboarding_quiz(
    user: dict = require_permission("dailyos.read"),
):
    """Return the onboarding quiz questions."""
    return onboarding_service.get_quiz()


@router_p3.post("/onboarding/submit", response_model=OnboardingResult)
async def submit_onboarding(
    data: OnboardingSubmitRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Submit quiz answers and receive recommended workflow + toggles."""
    return onboarding_service.submit(data)


# ======================== P4: Experiments ========================


@router_p3.get("/experiments", response_model=PaginatedResponse[ExperimentResponse])
async def list_experiments(
    space_id: str = Query("default"),
    status: str | None = Query(
        None, description="Filter by status: draft, running, completed, archived"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await experiment_service.list_experiments(db, space_id, pagination, status=status)


@router_p3.post("/experiments", response_model=ExperimentResponse, status_code=201)
async def create_experiment(
    data: ExperimentCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    instance = await experiment_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return experiment_service.to_response(instance)


@router_p3.put("/experiments/{experiment_id}", response_model=ExperimentResponse)
async def update_experiment(
    experiment_id: str,
    data: ExperimentUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    instance = await experiment_service.update(db, experiment_id, data, user_id=user.get("id"))
    if not instance:
        raise NotFoundError("Experiment not found", code="dailyos.experiment_not_found")
    await db.commit()
    return experiment_service.to_response(instance)


@router_p3.delete("/experiments/{experiment_id}", status_code=204)
async def delete_experiment(
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    if not await experiment_service.delete(db, experiment_id, user_id=user.get("id")):
        raise NotFoundError("Experiment not found", code="dailyos.experiment_not_found")
    await db.commit()


@router_p3.post("/experiments/{experiment_id}/start", response_model=ExperimentResponse)
async def start_experiment(
    experiment_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """Start a draft experiment (sets status=running, started_at=now)."""
    result = await experiment_service.start_experiment(db, experiment_id, space_id)
    await db.commit()
    return result


@router_p3.post("/experiments/{experiment_id}/end", response_model=ExperimentResponse)
async def end_experiment(
    experiment_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.write"),
):
    """End a running experiment and calculate results."""
    result = await experiment_service.end_experiment(db, experiment_id, space_id)
    await db.commit()
    return result


@router_p3.get("/experiments/{experiment_id}/results", response_model=ExperimentResultsResponse)
async def get_experiment_results(
    experiment_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("dailyos.read"),
):
    """Get experiment results comparison."""
    return await experiment_service.get_results(db, experiment_id, space_id)

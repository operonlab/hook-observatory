"""Daily OS P3+P4 Pydantic schemas.

Features: Eisenhower, Wizard, Templates, Gamification, Onboarding, Experiments.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.shared.schemas import SpaceScopedResponse

# ======================== P3a: Eisenhower ========================


class EisenhowerQuadrant(BaseModel):
    quadrant: Literal["q1", "q2", "q3", "q4"]
    label: str
    description: str
    items: list[dict] = Field(default_factory=list)
    item_count: int = 0


class EisenhowerResponse(BaseModel):
    q1: EisenhowerQuadrant
    q2: EisenhowerQuadrant
    q3: EisenhowerQuadrant
    q4: EisenhowerQuadrant
    total_items: int = 0


# ======================== P3b: Procrastination Wizard ========================


class WizardStartRequest(BaseModel):
    item_id: str
    space_id: str = "default"


class WizardRespondRequest(BaseModel):
    item_id: str
    step: int
    answer: str
    session_state: dict = Field(default_factory=dict)
    space_id: str = "default"


class WizardQuestion(BaseModel):
    step: int
    total_steps: int
    question: str
    hint: str | None = None
    session_state: dict = Field(default_factory=dict)


class WizardResult(BaseModel):
    completed: bool = True
    recommendation: Literal["decompose", "delegate", "defer", "do_now"]
    micro_task: str
    original_item_id: str
    reasoning: str


class WizardStepResponse(BaseModel):
    completed: bool = False
    question: WizardQuestion | None = None
    result: WizardResult | None = None


class InterventionType(BaseModel):
    id: str
    name: str
    description: str
    steps: int


class InterventionsResponse(BaseModel):
    interventions: list[InterventionType]


# ======================== P3c: Plan Templates ========================


class PlanTemplateCreate(BaseModel):
    slug: str
    name: str
    name_zh: str | None = None
    description: str | None = None
    items: list[dict] = Field(default_factory=list)
    method_ids: list[str] | None = None
    toggle_overrides: dict | None = None
    tags: list[str] | None = None


class PlanTemplateUpdate(BaseModel):
    slug: str | None = None
    name: str | None = None
    name_zh: str | None = None
    description: str | None = None
    items: list[dict] | None = None
    method_ids: list[str] | None = None
    toggle_overrides: dict | None = None
    tags: list[str] | None = None


class PlanTemplateResponse(SpaceScopedResponse):
    slug: str
    name: str
    name_zh: str | None = None
    description: str | None = None
    items: list[dict] = Field(default_factory=list)
    method_ids: list[str] | None = None
    toggle_overrides: dict | None = None
    tags: list[str] | None = None
    use_count: int = 0
    last_used_at: datetime | None = None
    deleted_at: datetime | None = None


class TemplateFromPlanRequest(BaseModel):
    slug: str
    name: str
    name_zh: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class TemplateApplyRequest(BaseModel):
    space_id: str = "default"
    plan_date: date | None = None
    context: str = "default"
    merge_mode: Literal["append", "replace"] = "append"


class TemplateApplyResponse(BaseModel):
    plan_id: str
    plan_date: date
    items_added: int
    total_items: int


# ======================== P3d: Gamification ========================


class GamificationStateResponse(SpaceScopedResponse):
    total_points: int = 0
    current_streak: int = 0
    longest_streak: int = 0
    last_streak_date: date | None = None
    level: int = 1
    achievements: list[dict] = Field(default_factory=list)
    reward_config: dict | None = None


class AwardPointsRequest(BaseModel):
    space_id: str = "default"
    points: int
    reason: str
    source_type: str  # task, frog, streak, bonus
    source_id: str | None = None
    multiplier: float = 1.0


class AwardPointsResponse(BaseModel):
    points_awarded: int
    effective_points: int
    multiplier: float
    new_total: int
    new_level: int
    new_achievements: list[dict] = Field(default_factory=list)


class PointHistoryResponse(SpaceScopedResponse):
    points: int
    reason: str
    source_type: str
    source_id: str | None = None
    multiplier: float = 1.0
    earned_at: datetime


class StreakResponse(BaseModel):
    current_streak: int
    longest_streak: int
    last_streak_date: date | None = None
    is_active_today: bool


# ======================== P3e: Onboarding Quiz ========================


class QuizOption(BaseModel):
    value: str
    label: str
    tags: list[str] = Field(default_factory=list)


class QuizQuestion(BaseModel):
    id: str
    question: str
    options: list[QuizOption]
    multi_select: bool = False


class QuizResponse(BaseModel):
    questions: list[QuizQuestion]
    version: str = "1.0"


class OnboardingSubmitRequest(BaseModel):
    space_id: str = "default"
    answers: dict[str, str | list[str]]  # question_id -> selected value(s)


class OnboardingResult(BaseModel):
    recommended_workflow_slug: str | None = None
    recommended_workflow_name: str | None = None
    recommended_toggles: list[str] = Field(default_factory=list)
    matched_tags: list[str] = Field(default_factory=list)
    description: str


# ======================== P4: Experiments ========================


class ExperimentCreate(BaseModel):
    name: str
    name_zh: str | None = None
    description: str | None = None
    variant_a: dict = Field(default_factory=dict)
    variant_b: dict = Field(default_factory=dict)
    duration_days: int = 7


class ExperimentUpdate(BaseModel):
    name: str | None = None
    name_zh: str | None = None
    description: str | None = None
    variant_a: dict | None = None
    variant_b: dict | None = None
    duration_days: int | None = None


class ExperimentResponse(SpaceScopedResponse):
    name: str
    name_zh: str | None = None
    description: str | None = None
    status: str = "draft"  # draft, running, completed, archived
    variant_a: dict = Field(default_factory=dict)
    variant_b: dict = Field(default_factory=dict)
    duration_days: int = 7
    started_at: datetime | None = None
    ended_at: datetime | None = None
    results: dict | None = None
    winner: str | None = None  # a, b, tie, inconclusive
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ExperimentResultsResponse(BaseModel):
    experiment_id: str
    name: str
    status: str
    winner: str | None = None
    variant_a_stats: dict = Field(default_factory=dict)
    variant_b_stats: dict = Field(default_factory=dict)
    analysis: str
    started_at: datetime | None = None
    ended_at: datetime | None = None

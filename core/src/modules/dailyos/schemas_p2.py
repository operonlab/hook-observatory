"""Daily OS P2 Pydantic schemas — Workflows, Pilot, Snippets, SmartLists, Rituals."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.shared.schemas import SpaceScopedResponse

# ======================== P2a: Workflows ========================


class WorkflowCreate(BaseModel):
    slug: str
    name: str
    name_zh: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    category: str = "methodology"
    method_ids: list[str] | None = None
    toggle_overrides: dict | None = None
    snippet_ids: list[str] | None = None
    tags: list[str] | None = None


class WorkflowUpdate(BaseModel):
    slug: str | None = None
    name: str | None = None
    name_zh: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    category: str | None = None
    method_ids: list[str] | None = None
    toggle_overrides: dict | None = None
    snippet_ids: list[str] | None = None
    tags: list[str] | None = None


class WorkflowResponse(SpaceScopedResponse):
    slug: str
    name: str
    name_zh: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    is_preset: bool = False
    category: str = "methodology"
    method_ids: list[str] | None = None
    toggle_overrides: dict | None = None
    snippet_ids: list[str] | None = None
    tags: list[str] | None = None
    is_active: bool = False
    rating: float | None = None
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class WorkflowRateRequest(BaseModel):
    rating: float = Field(..., ge=1, le=5)


class WorkflowActivateResponse(BaseModel):
    workflow: WorkflowResponse
    applied_method_ids: list[str] = Field(default_factory=list)
    applied_toggle_overrides: dict = Field(default_factory=dict)
    applied_snippet_ids: list[str] = Field(default_factory=list)


# ======================== P2b: Pilot Method ========================


class PilotStateUpdate(BaseModel):
    flight_mode: Literal["sprint", "cruise", "glide", "emergency"] | None = None
    cognitive_fuel_spent: float | None = Field(None, ge=0, le=100)
    time_spent_min: int | None = Field(None, ge=0)
    cognitive_fuel_budget: float | None = Field(None, ge=0, le=100)
    time_budget_min: int | None = Field(None, ge=0)


class PilotDecisionRequest(BaseModel):
    description: str | None = None
    cognitive_cost: int = Field(default=1, ge=1, le=5)


class PilotStateResponse(SpaceScopedResponse):
    state_date: date
    flight_mode: str = "cruise"
    cognitive_fuel_budget: float = 100.0
    cognitive_fuel_spent: float = 0.0
    time_budget_min: int = 480
    time_spent_min: int = 0
    verify_level: str = "normal"
    ratchet_history: list[dict] | None = None
    black_box: dict | None = None
    decision_count: int = 0
    decision_fatigue_score: float | None = None
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PilotRatchetResponse(BaseModel):
    verify_level: Literal["skip", "light", "normal", "thorough"]
    fuel_ratio: float
    cognitive_fuel_spent: float
    cognitive_fuel_budget: float
    rationale: str


class PilotDecisionResponse(BaseModel):
    decision_count: int
    decision_fatigue_score: float
    verify_level: str
    state: PilotStateResponse


# ======================== P2c: Snippets ========================


class SnippetCreate(BaseModel):
    slug: str
    name: str
    name_zh: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    toggle_keys: list[str] | None = None
    config_patch: dict | None = None
    tags: list[str] | None = None


class SnippetUpdate(BaseModel):
    slug: str | None = None
    name: str | None = None
    name_zh: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    toggle_keys: list[str] | None = None
    config_patch: dict | None = None
    tags: list[str] | None = None


class SnippetResponse(SpaceScopedResponse):
    slug: str
    name: str
    name_zh: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    is_preset: bool = False
    toggle_keys: list[str] | None = None
    config_patch: dict | None = None
    tags: list[str] | None = None
    is_active: bool = False
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SnippetActivateResponse(BaseModel):
    snippet: SnippetResponse
    applied_toggle_keys: list[str] = Field(default_factory=list)
    applied_config_patch: dict = Field(default_factory=dict)


# ======================== P2d: Smart Lists ========================


class RpnToken(BaseModel):
    type: Literal["field", "logic"]
    field: str | None = None
    op: str | None = None
    value: object = None


class SmartListCreate(BaseModel):
    slug: str
    name: str
    name_zh: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    filter_expr: list[dict] = Field(default_factory=list)
    sort_by: str = "priority"
    group_by: str | None = None
    source_modules: list[str] | None = None
    tags: list[str] | None = None


class SmartListUpdate(BaseModel):
    slug: str | None = None
    name: str | None = None
    name_zh: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    filter_expr: list[dict] | None = None
    sort_by: str | None = None
    group_by: str | None = None
    source_modules: list[str] | None = None
    tags: list[str] | None = None


class SmartListResponse(SpaceScopedResponse):
    slug: str
    name: str
    name_zh: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    filter_expr: list[dict] = Field(default_factory=list)
    sort_by: str = "priority"
    group_by: str | None = None
    is_preset: bool = False
    source_modules: list[str] | None = None
    tags: list[str] | None = None
    deleted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SmartListExecuteResponse(BaseModel):
    smart_list_id: str
    total_matched: int
    items: list[dict]
    execution_time_ms: float | None = None


class SmartListPresetItem(BaseModel):
    slug: str
    name: str
    name_zh: str | None = None
    description: str | None = None
    filter_expr: list[dict]
    sort_by: str = "priority"


# ======================== P2e: Guided Daily Ritual ========================


class RitualChecklistItem(BaseModel):
    key: str
    label: str
    label_zh: str | None = None
    completed: bool = False
    optional: bool = False


class MorningRitualResponse(BaseModel):
    plan_date: date
    checklist: list[RitualChecklistItem]
    suggestions: list[str] = Field(default_factory=list)
    pilot_state: PilotStateResponse | None = None
    active_workflow: WorkflowResponse | None = None


class EveningRitualResponse(BaseModel):
    plan_date: date
    checklist: list[RitualChecklistItem]
    review_data: dict = Field(default_factory=dict)
    carry_forward: list[dict] = Field(default_factory=list)
    pilot_summary: dict | None = None


class RitualStatusResponse(BaseModel):
    plan_date: date
    morning_completed: bool = False
    morning_completed_at: datetime | None = None
    evening_completed: bool = False
    evening_completed_at: datetime | None = None
    morning_checklist: list[RitualChecklistItem] = Field(default_factory=list)
    evening_checklist: list[RitualChecklistItem] = Field(default_factory=list)

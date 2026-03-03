"""Pydantic request/response models for Agent Metrics API."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────


class TaskMode(StrEnum):
    LINEAR = "linear"
    DAG = "dag"
    DEBATE = "debate"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in-progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class OrchePattern(StrEnum):
    SOLO = "solo"
    PIPELINE = "pipeline"
    RACE = "race"
    SWARM = "swarm"
    ESCALATION = "escalation"


class Budget(StrEnum):
    MINIMIZE = "minimize"
    BALANCED = "balanced"
    MAXIMIZE = "maximize_quality"


# ── Maestro Dispatch ──────────────────────────────────────────────


class PlanRequest(BaseModel):
    task: str
    pattern: OrchePattern | None = None
    budget: Budget = Budget.BALANCED


class DispatchRequest(BaseModel):
    task: str
    pattern: OrchePattern | None = None
    budget: Budget = Budget.BALANCED
    cwd: str = ""
    timeout: int = 300
    ratio: str = ""


# ── Team-Task Projects ───────────────────────────────────────────


class ProjectCreate(BaseModel):
    name: str
    mode: TaskMode = TaskMode.DAG
    goal: str = ""
    pipeline: str = ""
    workspace: str = ""


class TaskAdd(BaseModel):
    task_id: str
    agent: str = ""
    description: str = ""
    deps: str = ""


class DebaterAdd(BaseModel):
    debater_id: str
    agent: str = ""
    perspective: str = ""


class TaskUpdate(BaseModel):
    status: TaskStatus


class TaskResult(BaseModel):
    text: str


class RoundAction(BaseModel):
    action: str  # start | submit | cross-review | synthesize | status
    debater_id: str = ""
    text: str = ""


# ── Session Tracking (ported from V1) ────────────────────────────


class ContextInfo(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    window_size: int = 0
    used_pct: float = 0.0


class IngestRequest(BaseModel):
    sid: str = Field(..., min_length=1, max_length=16)
    session_id: str = ""
    cli: str = "claude"
    cost: float = 0.0
    model_id: str = ""
    model_display: str = ""
    project: str = ""
    context: ContextInfo = ContextInfo()


class IngestResponse(BaseModel):
    total: float
    sessions: int
    daily: float


class SessionInfo(BaseModel):
    id: str
    sid: str
    cli: str = "claude"
    model_id: str
    model_display: str
    project: str
    cost_usd: float
    context_used_pct: float
    context_window_size: int
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    first_seen: str
    last_seen: str
    is_active: bool


class CurrentResponse(BaseModel):
    date: str
    total_cost_usd: float
    active_sessions: int
    sessions: list[SessionInfo]


class DailySummaryResponse(BaseModel):
    date: str
    total_cost_usd: float
    total_sessions: int
    peak_concurrent: int
    total_input_tokens: int
    total_output_tokens: int
    avg_context_pct: float
    max_context_pct: float


# ── LLM Usage (merged from llm-usage station) ────────────────────


class SubscriptionInfo(BaseModel):
    cli: str
    provider: str
    plan: str
    monthly_cost_usd: float = 0.0
    quota_5h_pct: int | None = None
    quota_7d_pct: int | None = None
    current_mode: str | None = None
    source: str = "unknown"


class BudgetInfo(BaseModel):
    budget_usd: float
    used_usd: float
    used_pct: float
    remaining_usd: float
    warning: bool = False
    warning_threshold_pct: float = 80.0
    days_elapsed: int = 0


class CacheStats(BaseModel):
    cache_hit_rate: float = 0.0
    total_cache_read: int = 0
    total_cache_creation: int = 0
    estimated_savings_usd: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0


class TrendEntry(BaseModel):
    date: str
    cost_usd: float
    tokens_in: int = 0
    tokens_out: int = 0
    cumulative_cost_usd: float = 0.0
    cost_7d_avg_usd: float | None = None


class ModelBreakdown(BaseModel):
    model: str
    provider: str = "anthropic"
    requests: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    cost_usd: float = 0.0
    cache_hit_rate: float = 0.0
    pct_of_total: float = 0.0


class UsageSummary(BaseModel):
    type: str = "summary"
    timestamp: str
    period: str
    subscription: dict
    api: dict
    combined: dict

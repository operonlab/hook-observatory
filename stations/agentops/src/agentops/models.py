"""Pydantic request/response models for AgentOps API."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


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

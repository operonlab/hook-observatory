"""Daily OS P2 service layer — Workflows, Pilot Method, Snippets, SmartLists, Rituals."""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.errors import BadRequestError, NotFoundError
from src.shared.models import _uuid7_hex

from .models import BacklogItem, DailyPlan, PilotState, SmartList, Snippet, Workflow
from .schemas_p2 import (
    EveningRitualResponse,
    MorningRitualResponse,
    PilotDecisionResponse,
    PilotRatchetResponse,
    PilotStateResponse,
    PilotStateUpdate,
    RitualChecklistItem,
    RitualStatusResponse,
    SmartListCreate,
    SmartListExecuteResponse,
    SmartListPresetItem,
    SmartListResponse,
    SmartListUpdate,
    SnippetActivateResponse,
    SnippetCreate,
    SnippetResponse,
    SnippetUpdate,
    WorkflowActivateResponse,
    WorkflowCreate,
    WorkflowResponse,
    WorkflowUpdate,
)

logger = logging.getLogger(__name__)

# ======================== P2a: Workflow Service ========================

_WORKFLOW_PRESETS: list[dict] = [
    {
        "slug": "gtd",
        "name": "GTD",
        "name_zh": "完成事情法",
        "description": "David Allen's Getting Things Done methodology",
        "icon": "inbox",
        "color": "#89b4fa",
        "category": "methodology",
        "method_ids": [],
        "toggle_overrides": {"weekly_review": True, "someday_maybe": True},
        "snippet_ids": [],
        "tags": ["productivity", "classic"],
    },
    {
        "slug": "timeblocking",
        "name": "Time Blocking",
        "name_zh": "時間分塊法",
        "description": "Cal Newport's deep work time blocking approach",
        "icon": "calendar",
        "color": "#a6e3a1",
        "category": "methodology",
        "method_ids": [],
        "toggle_overrides": {"time_blocks": True, "deep_work": True},
        "snippet_ids": [],
        "tags": ["focus", "deep-work"],
    },
    {
        "slug": "eat-the-frog",
        "name": "Eat the Frog",
        "name_zh": "吃掉青蛙法",
        "description": "Tackle the hardest task first thing in the morning",
        "icon": "zap",
        "color": "#f38ba8",
        "category": "methodology",
        "method_ids": [],
        "toggle_overrides": {"frog_first": True},
        "snippet_ids": [],
        "tags": ["priority", "morning"],
    },
]


class WorkflowService:
    """CRUD + activation for strategy bundles (workflows)."""

    async def list_workflows(
        self,
        db: AsyncSession,
        space_id: str,
        include_presets: bool = True,
    ) -> list[WorkflowResponse]:
        stmt = select(Workflow).where(
            Workflow.space_id == space_id,
            Workflow.deleted_at.is_(None),
        )
        if not include_presets:
            stmt = stmt.where(Workflow.is_preset.is_(False))
        stmt = stmt.order_by(Workflow.created_at.desc())
        rows = (await db.execute(stmt)).scalars().all()
        return [self._to_response(w) for w in rows]

    async def get(self, db: AsyncSession, workflow_id: str) -> Workflow | None:
        stmt = select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.deleted_at.is_(None),
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        space_id: str,
        data: WorkflowCreate,
        user_id: str | None = None,
    ) -> WorkflowResponse:
        # Check slug uniqueness
        existing = await self._get_by_slug(db, space_id, data.slug)
        if existing:
            raise BadRequestError(
                f"Workflow slug '{data.slug}' already exists",
                code="dailyos.workflow_slug_conflict",
            )
        now = datetime.now(UTC)
        wf = Workflow(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            created_at=now,
            updated_at=now,
            slug=data.slug,
            name=data.name,
            name_zh=data.name_zh,
            description=data.description,
            icon=data.icon,
            color=data.color,
            is_preset=False,
            category=data.category,
            method_ids=data.method_ids,
            toggle_overrides=data.toggle_overrides,
            snippet_ids=data.snippet_ids,
            tags=data.tags,
            is_active=False,
        )
        db.add(wf)
        await db.flush()
        return self._to_response(wf)

    async def update(
        self,
        db: AsyncSession,
        workflow_id: str,
        data: WorkflowUpdate,
        user_id: str | None = None,
    ) -> WorkflowResponse:
        wf = await self.get(db, workflow_id)
        if not wf:
            raise NotFoundError("Workflow not found", code="dailyos.workflow_not_found")
        if wf.is_preset:
            raise BadRequestError(
                "Cannot modify preset workflows",
                code="dailyos.workflow_preset_readonly",
            )
        changes = data.model_dump(exclude_unset=True)
        if "slug" in changes and changes["slug"] != wf.slug:
            existing = await self._get_by_slug(db, wf.space_id, changes["slug"])
            if existing:
                raise BadRequestError(
                    f"Workflow slug '{changes['slug']}' already exists",
                    code="dailyos.workflow_slug_conflict",
                )
        for field, value in changes.items():
            setattr(wf, field, value)
        wf.updated_at = datetime.now(UTC)
        await db.flush()
        return self._to_response(wf)

    async def delete(
        self,
        db: AsyncSession,
        workflow_id: str,
        user_id: str | None = None,
    ) -> None:
        wf = await self.get(db, workflow_id)
        if not wf:
            raise NotFoundError("Workflow not found", code="dailyos.workflow_not_found")
        if wf.is_preset:
            raise BadRequestError(
                "Cannot delete preset workflows",
                code="dailyos.workflow_preset_readonly",
            )
        wf.deleted_at = datetime.now(UTC)
        await db.flush()

    async def activate(
        self,
        db: AsyncSession,
        workflow_id: str,
        space_id: str,
        user_id: str | None = None,
    ) -> WorkflowActivateResponse:
        wf = await self.get(db, workflow_id)
        if not wf:
            raise NotFoundError("Workflow not found", code="dailyos.workflow_not_found")

        # Deactivate current active workflows in same space
        stmt = select(Workflow).where(
            Workflow.space_id == space_id,
            Workflow.is_active.is_(True),
            Workflow.deleted_at.is_(None),
        )
        active_wfs = (await db.execute(stmt)).scalars().all()
        for aw in active_wfs:
            aw.is_active = False
            aw.updated_at = datetime.now(UTC)

        wf.is_active = True
        wf.updated_at = datetime.now(UTC)
        await db.flush()

        return WorkflowActivateResponse(
            workflow=self._to_response(wf),
            applied_method_ids=list(wf.method_ids or []),
            applied_toggle_overrides=dict(wf.toggle_overrides or {}),
            applied_snippet_ids=list(wf.snippet_ids or []),
        )

    async def rate(
        self,
        db: AsyncSession,
        workflow_id: str,
        rating: float,
    ) -> WorkflowResponse:
        if not (1 <= rating <= 5):
            raise BadRequestError("Rating must be between 1 and 5", code="dailyos.invalid_rating")
        wf = await self.get(db, workflow_id)
        if not wf:
            raise NotFoundError("Workflow not found", code="dailyos.workflow_not_found")
        wf.rating = rating
        wf.updated_at = datetime.now(UTC)
        await db.flush()
        return self._to_response(wf)

    async def _get_by_slug(self, db: AsyncSession, space_id: str, slug: str) -> Workflow | None:
        stmt = select(Workflow).where(
            Workflow.space_id == space_id,
            Workflow.slug == slug,
            Workflow.deleted_at.is_(None),
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    def _to_response(self, wf: Workflow) -> WorkflowResponse:
        return WorkflowResponse(
            id=wf.id,
            space_id=wf.space_id,
            created_by=wf.created_by,
            created_at=wf.created_at,
            updated_at=wf.updated_at,
            slug=wf.slug,
            name=wf.name,
            name_zh=wf.name_zh,
            description=wf.description,
            icon=wf.icon,
            color=wf.color,
            is_preset=wf.is_preset,
            category=wf.category,
            method_ids=wf.method_ids,
            toggle_overrides=wf.toggle_overrides,
            snippet_ids=wf.snippet_ids,
            tags=wf.tags,
            is_active=wf.is_active,
            rating=wf.rating,
            deleted_at=wf.deleted_at,
        )


# ======================== P2b: Pilot Method Service ========================

_RATCHET_LEVELS = [
    (0.25, "skip"),
    (0.50, "light"),
    (0.75, "normal"),
    (1.01, "thorough"),
]


class PilotService:
    """Dual-track capacity state — cognitive fuel + flight mode per day."""

    async def get_or_create_today(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None = None,
    ) -> PilotState:
        today = date.today()
        stmt = select(PilotState).where(
            PilotState.space_id == space_id,
            PilotState.state_date == today,
            PilotState.deleted_at.is_(None),
        )
        state = (await db.execute(stmt)).scalar_one_or_none()
        if state:
            return state

        # Try to pull defaults from capacity history (latest entry)
        from .models import CapacityHistory

        time_budget = 480
        fuel_budget = 100.0
        stmt_ch = (
            select(CapacityHistory)
            .where(
                CapacityHistory.space_id == space_id,
                CapacityHistory.deleted_at.is_(None),
            )
            .order_by(CapacityHistory.log_date.desc())
            .limit(1)
        )
        ch = (await db.execute(stmt_ch)).scalar_one_or_none()
        if ch:
            if ch.budget_type == "time":
                time_budget = int(ch.planned_value) if ch.planned_value else time_budget
            elif ch.budget_type == "cognitive":
                fuel_budget = ch.planned_value if ch.planned_value else fuel_budget

        now = datetime.now(UTC)
        state = PilotState(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            created_at=now,
            updated_at=now,
            state_date=today,
            flight_mode="cruise",
            cognitive_fuel_budget=fuel_budget,
            cognitive_fuel_spent=0.0,
            time_budget_min=time_budget,
            time_spent_min=0,
            verify_level="normal",
            decision_count=0,
        )
        db.add(state)
        await db.flush()
        return state

    async def update_today(
        self,
        db: AsyncSession,
        space_id: str,
        data: PilotStateUpdate,
        user_id: str | None = None,
    ) -> PilotState:
        state = await self.get_or_create_today(db, space_id, user_id=user_id)
        changes = data.model_dump(exclude_unset=True)

        # Validate flight_mode
        valid_modes = {"sprint", "cruise", "glide", "emergency"}
        if "flight_mode" in changes and changes["flight_mode"] not in valid_modes:
            raise BadRequestError(
                f"Invalid flight_mode: {changes['flight_mode']}",
                code="dailyos.invalid_flight_mode",
            )

        for field, value in changes.items():
            setattr(state, field, value)

        # Recalculate verify_level after fuel update
        state.verify_level = self._calculate_verify_level(
            state.cognitive_fuel_spent, state.cognitive_fuel_budget
        )
        state.updated_at = datetime.now(UTC)
        await db.flush()
        return state

    async def record_decision(
        self,
        db: AsyncSession,
        space_id: str,
        description: str | None = None,
        fuel_cost: float = 1.0,
        user_id: str | None = None,
    ) -> PilotDecisionResponse:
        state = await self.get_or_create_today(db, space_id, user_id=user_id)

        # Increment decision count and add fuel cost
        state.decision_count = (state.decision_count or 0) + 1
        state.cognitive_fuel_spent = min(
            state.cognitive_fuel_budget,
            (state.cognitive_fuel_spent or 0) + fuel_cost,
        )

        # Recalculate fatigue score: count / (budget - spent + 1)
        remaining = state.cognitive_fuel_budget - state.cognitive_fuel_spent
        state.decision_fatigue_score = state.decision_count / (remaining + 1)

        # Recalculate verify_level
        state.verify_level = self._calculate_verify_level(
            state.cognitive_fuel_spent, state.cognitive_fuel_budget
        )

        # Append ratchet history
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "decision_count": state.decision_count,
            "fuel_spent": state.cognitive_fuel_spent,
            "verify_level": state.verify_level,
            "description": description,
        }
        history = list(state.ratchet_history or [])
        history.append(entry)
        state.ratchet_history = history
        state.updated_at = datetime.now(UTC)
        await db.flush()

        return PilotDecisionResponse(
            decision_count=state.decision_count,
            decision_fatigue_score=state.decision_fatigue_score,
            verify_level=state.verify_level,
            state=self._to_response(state),
        )

    async def get_history(
        self,
        db: AsyncSession,
        space_id: str,
        date_from: date,
        date_to: date,
    ) -> list[PilotStateResponse]:
        stmt = (
            select(PilotState)
            .where(
                PilotState.space_id == space_id,
                PilotState.state_date >= date_from,
                PilotState.state_date <= date_to,
                PilotState.deleted_at.is_(None),
            )
            .order_by(PilotState.state_date.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [self._to_response(r) for r in rows]

    async def calculate_ratchet(
        self,
        db: AsyncSession,
        space_id: str,
    ) -> PilotRatchetResponse:
        stmt = select(PilotState).where(
            PilotState.space_id == space_id,
            PilotState.state_date == date.today(),
            PilotState.deleted_at.is_(None),
        )
        state = (await db.execute(stmt)).scalar_one_or_none()
        if not state:
            return PilotRatchetResponse(
                verify_level="normal",
                fuel_ratio=0.0,
                cognitive_fuel_spent=0.0,
                cognitive_fuel_budget=100.0,
                rationale="No pilot state for today — using default",
            )

        fuel_ratio = (
            state.cognitive_fuel_spent / state.cognitive_fuel_budget
            if state.cognitive_fuel_budget > 0
            else 0.0
        )
        verify_level = self._calculate_verify_level(
            state.cognitive_fuel_spent, state.cognitive_fuel_budget
        )
        rationale_map = {
            "skip": "Fuel ratio < 25% — low decision fatigue, skip validation",
            "light": "Fuel ratio 25-50% — moderate fatigue, light check",
            "normal": "Fuel ratio 50-75% — significant fatigue, normal validation",
            "thorough": "Fuel ratio >= 75% — high fatigue, thorough review required",
        }
        return PilotRatchetResponse(
            verify_level=verify_level,  # type: ignore[arg-type]
            fuel_ratio=round(fuel_ratio, 4),
            cognitive_fuel_spent=state.cognitive_fuel_spent,
            cognitive_fuel_budget=state.cognitive_fuel_budget,
            rationale=rationale_map.get(verify_level, ""),
        )

    async def save_black_box(
        self,
        db: AsyncSession,
        space_id: str,
        plan_completion: float | None = None,
        method_used: str | None = None,
    ) -> PilotStateResponse:
        state = await self.get_or_create_today(db, space_id)
        snapshot = {
            "snapshot_at": datetime.now(UTC).isoformat(),
            "flight_mode": state.flight_mode,
            "cognitive_fuel_budget": state.cognitive_fuel_budget,
            "cognitive_fuel_spent": state.cognitive_fuel_spent,
            "time_budget_min": state.time_budget_min,
            "time_spent_min": state.time_spent_min,
            "decision_count": state.decision_count,
            "decision_fatigue_score": state.decision_fatigue_score,
            "verify_level": state.verify_level,
            "plan_completion": plan_completion,
            "method_used": method_used,
        }
        state.black_box = snapshot
        state.updated_at = datetime.now(UTC)
        await db.flush()
        return self._to_response(state)

    def _calculate_verify_level(self, spent: float, budget: float) -> str:
        if budget <= 0:
            return "normal"
        ratio = spent / budget
        for threshold, level in _RATCHET_LEVELS:
            if ratio < threshold:
                return level
        return "thorough"

    def _to_response(self, state: PilotState) -> PilotStateResponse:
        return PilotStateResponse(
            id=state.id,
            space_id=state.space_id,
            created_by=state.created_by,
            created_at=state.created_at,
            updated_at=state.updated_at,
            state_date=state.state_date,
            flight_mode=state.flight_mode,
            cognitive_fuel_budget=state.cognitive_fuel_budget,
            cognitive_fuel_spent=state.cognitive_fuel_spent,
            time_budget_min=state.time_budget_min,
            time_spent_min=state.time_spent_min,
            verify_level=state.verify_level,
            ratchet_history=state.ratchet_history,
            black_box=state.black_box,
            decision_count=state.decision_count,
            decision_fatigue_score=state.decision_fatigue_score,
            deleted_at=state.deleted_at,
        )


# ======================== P2c: Snippet Service ========================


class SnippetService:
    """CRUD + activation for additive feature fragments."""

    async def list_snippets(
        self,
        db: AsyncSession,
        space_id: str,
        include_presets: bool = True,
    ) -> list[SnippetResponse]:
        stmt = select(Snippet).where(
            Snippet.space_id == space_id,
            Snippet.deleted_at.is_(None),
        )
        if not include_presets:
            stmt = stmt.where(Snippet.is_preset.is_(False))
        stmt = stmt.order_by(Snippet.created_at.desc())
        rows = (await db.execute(stmt)).scalars().all()
        return [self._to_response(s) for s in rows]

    async def get(self, db: AsyncSession, snippet_id: str) -> Snippet | None:
        stmt = select(Snippet).where(
            Snippet.id == snippet_id,
            Snippet.deleted_at.is_(None),
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        space_id: str,
        data: SnippetCreate,
        user_id: str | None = None,
    ) -> SnippetResponse:
        existing = await self._get_by_slug(db, space_id, data.slug)
        if existing:
            raise BadRequestError(
                f"Snippet slug '{data.slug}' already exists",
                code="dailyos.snippet_slug_conflict",
            )
        now = datetime.now(UTC)
        sn = Snippet(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            created_at=now,
            updated_at=now,
            slug=data.slug,
            name=data.name,
            name_zh=data.name_zh,
            description=data.description,
            icon=data.icon,
            color=data.color,
            is_preset=False,
            toggle_keys=data.toggle_keys,
            config_patch=data.config_patch,
            tags=data.tags,
            is_active=False,
        )
        db.add(sn)
        await db.flush()
        return self._to_response(sn)

    async def update(
        self,
        db: AsyncSession,
        snippet_id: str,
        data: SnippetUpdate,
        user_id: str | None = None,
    ) -> SnippetResponse:
        sn = await self.get(db, snippet_id)
        if not sn:
            raise NotFoundError("Snippet not found", code="dailyos.snippet_not_found")
        if sn.is_preset:
            raise BadRequestError(
                "Cannot modify preset snippets",
                code="dailyos.snippet_preset_readonly",
            )
        changes = data.model_dump(exclude_unset=True)
        if "slug" in changes and changes["slug"] != sn.slug:
            existing = await self._get_by_slug(db, sn.space_id, changes["slug"])
            if existing:
                raise BadRequestError(
                    f"Snippet slug '{changes['slug']}' already exists",
                    code="dailyos.snippet_slug_conflict",
                )
        for field, value in changes.items():
            setattr(sn, field, value)
        sn.updated_at = datetime.now(UTC)
        await db.flush()
        return self._to_response(sn)

    async def delete(
        self,
        db: AsyncSession,
        snippet_id: str,
        user_id: str | None = None,
    ) -> None:
        sn = await self.get(db, snippet_id)
        if not sn:
            raise NotFoundError("Snippet not found", code="dailyos.snippet_not_found")
        if sn.is_preset:
            raise BadRequestError(
                "Cannot delete preset snippets",
                code="dailyos.snippet_preset_readonly",
            )
        sn.deleted_at = datetime.now(UTC)
        await db.flush()

    async def activate(
        self,
        db: AsyncSession,
        snippet_id: str,
        user_id: str | None = None,
    ) -> SnippetActivateResponse:
        sn = await self.get(db, snippet_id)
        if not sn:
            raise NotFoundError("Snippet not found", code="dailyos.snippet_not_found")
        sn.is_active = True
        sn.updated_at = datetime.now(UTC)
        await db.flush()
        return SnippetActivateResponse(
            snippet=self._to_response(sn),
            applied_toggle_keys=list(sn.toggle_keys or []),
            applied_config_patch=dict(sn.config_patch or {}),
        )

    async def deactivate(
        self,
        db: AsyncSession,
        snippet_id: str,
        user_id: str | None = None,
    ) -> SnippetResponse:
        sn = await self.get(db, snippet_id)
        if not sn:
            raise NotFoundError("Snippet not found", code="dailyos.snippet_not_found")
        sn.is_active = False
        sn.updated_at = datetime.now(UTC)
        await db.flush()
        return self._to_response(sn)

    async def _get_by_slug(self, db: AsyncSession, space_id: str, slug: str) -> Snippet | None:
        stmt = select(Snippet).where(
            Snippet.space_id == space_id,
            Snippet.slug == slug,
            Snippet.deleted_at.is_(None),
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    def _to_response(self, sn: Snippet) -> SnippetResponse:
        return SnippetResponse(
            id=sn.id,
            space_id=sn.space_id,
            created_by=sn.created_by,
            created_at=sn.created_at,
            updated_at=sn.updated_at,
            slug=sn.slug,
            name=sn.name,
            name_zh=sn.name_zh,
            description=sn.description,
            icon=sn.icon,
            color=sn.color,
            is_preset=sn.is_preset,
            toggle_keys=sn.toggle_keys,
            config_patch=sn.config_patch,
            tags=sn.tags,
            is_active=sn.is_active,
            deleted_at=sn.deleted_at,
        )


# ======================== P2d: Smart List Service ========================

_PRESET_SMART_LISTS: list[SmartListPresetItem] = [
    SmartListPresetItem(
        slug="eisenhower-q1",
        name="Eisenhower Q1: Urgent+Important",
        name_zh="艾森豪 Q1: 緊急且重要",
        description="Tasks that are both urgent and important — do immediately",
        filter_expr=[
            {"type": "field", "field": "priority", "op": "in", "value": ["urgent"]},
            {"type": "field", "field": "is_frog", "op": "eq", "value": True},
            {"type": "logic", "op": "OR"},
        ],
        sort_by="due_date",
    ),
    SmartListPresetItem(
        slug="eisenhower-q2",
        name="Eisenhower Q2: Not Urgent+Important",
        name_zh="艾森豪 Q2: 重要但不緊急",
        description="Schedule these — strategic and developmental tasks",
        filter_expr=[
            {"type": "field", "field": "priority", "op": "in", "value": ["high"]},
            {"type": "field", "field": "funnel_layer", "op": "in", "value": ["ready", "master"]},
            {"type": "logic", "op": "AND"},
        ],
        sort_by="priority",
    ),
    SmartListPresetItem(
        slug="next-actions",
        name="Next Actions",
        name_zh="下一步行動",
        description="Ready tasks with no blockers — GTD next actions list",
        filter_expr=[
            {"type": "field", "field": "funnel_layer", "op": "eq", "value": "ready"},
        ],
        sort_by="priority",
    ),
    SmartListPresetItem(
        slug="due-today",
        name="Due Today",
        name_zh="今日到期",
        description="Tasks due on or before today",
        filter_expr=[
            {"type": "field", "field": "due_date", "op": "within_days", "value": 0},
        ],
        sort_by="due_date",
    ),
    SmartListPresetItem(
        slug="quick-wins",
        name="Quick Wins",
        name_zh="快速勝利",
        description="Short, low-cognitive-cost tasks for momentum",
        filter_expr=[
            {"type": "field", "field": "duration_min", "op": "lte", "value": 30},
            {"type": "field", "field": "cognitive_cost", "op": "lte", "value": 2},
            {"type": "logic", "op": "AND"},
        ],
        sort_by="duration_min",
    ),
]

_FIELD_OPS = {
    "eq",
    "neq",
    "in",
    "not_in",
    "gt",
    "gte",
    "lt",
    "lte",
    "within_days",
    "contains",
}
_ALLOWED_FIELDS = {
    "priority",
    "funnel_layer",
    "labels",
    "energy_level",
    "duration_min",
    "cognitive_cost",
    "do_date",
    "due_date",
    "start_date",
    "is_frog",
    "defer_count",
    "source_module",
}


class SmartListService:
    """CRUD + RPN filter execution for smart lists."""

    async def list_smart_lists(
        self,
        db: AsyncSession,
        space_id: str,
    ) -> list[SmartListResponse]:
        stmt = (
            select(SmartList)
            .where(SmartList.space_id == space_id, SmartList.deleted_at.is_(None))
            .order_by(SmartList.created_at.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [self._to_response(sl) for sl in rows]

    async def get(self, db: AsyncSession, smart_list_id: str) -> SmartList | None:
        stmt = select(SmartList).where(
            SmartList.id == smart_list_id,
            SmartList.deleted_at.is_(None),
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        space_id: str,
        data: SmartListCreate,
        user_id: str | None = None,
    ) -> SmartListResponse:
        existing = await self._get_by_slug(db, space_id, data.slug)
        if existing:
            raise BadRequestError(
                f"SmartList slug '{data.slug}' already exists",
                code="dailyos.smart_list_slug_conflict",
            )
        self._validate_filter_expr(data.filter_expr)
        now = datetime.now(UTC)
        sl = SmartList(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            created_at=now,
            updated_at=now,
            slug=data.slug,
            name=data.name,
            name_zh=data.name_zh,
            description=data.description,
            icon=data.icon,
            color=data.color,
            filter_expr=data.filter_expr,
            sort_by=data.sort_by,
            group_by=data.group_by,
            is_preset=False,
            source_modules=data.source_modules,
            tags=data.tags,
        )
        db.add(sl)
        await db.flush()
        return self._to_response(sl)

    async def update(
        self,
        db: AsyncSession,
        smart_list_id: str,
        data: SmartListUpdate,
        user_id: str | None = None,
    ) -> SmartListResponse:
        sl = await self.get(db, smart_list_id)
        if not sl:
            raise NotFoundError("SmartList not found", code="dailyos.smart_list_not_found")
        if sl.is_preset:
            raise BadRequestError(
                "Cannot modify preset smart lists",
                code="dailyos.smart_list_preset_readonly",
            )
        changes = data.model_dump(exclude_unset=True)
        if "slug" in changes and changes["slug"] != sl.slug:
            existing = await self._get_by_slug(db, sl.space_id, changes["slug"])
            if existing:
                raise BadRequestError(
                    f"SmartList slug '{changes['slug']}' already exists",
                    code="dailyos.smart_list_slug_conflict",
                )
        if "filter_expr" in changes:
            self._validate_filter_expr(changes["filter_expr"])
        for field, value in changes.items():
            setattr(sl, field, value)
        sl.updated_at = datetime.now(UTC)
        await db.flush()
        return self._to_response(sl)

    async def delete(
        self,
        db: AsyncSession,
        smart_list_id: str,
        user_id: str | None = None,
    ) -> None:
        sl = await self.get(db, smart_list_id)
        if not sl:
            raise NotFoundError("SmartList not found", code="dailyos.smart_list_not_found")
        if sl.is_preset:
            raise BadRequestError(
                "Cannot delete preset smart lists",
                code="dailyos.smart_list_preset_readonly",
            )
        sl.deleted_at = datetime.now(UTC)
        await db.flush()

    async def execute(
        self,
        db: AsyncSession,
        smart_list_id: str,
        space_id: str,
    ) -> SmartListExecuteResponse:
        sl = await self.get(db, smart_list_id)
        if not sl:
            raise NotFoundError("SmartList not found", code="dailyos.smart_list_not_found")

        t_start = time.monotonic()
        # Fetch backlog items
        stmt = select(BacklogItem).where(
            BacklogItem.space_id == space_id,
            BacklogItem.deleted_at.is_(None),
        )
        all_items = (await db.execute(stmt)).scalars().all()
        items_as_dicts = [self._backlog_to_dict(item) for item in all_items]
        matched = self.execute_filter(sl.filter_expr, items_as_dicts)

        # Apply sorting
        sort_field = sl.sort_by or "priority"
        _priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "someday": 4}
        if sort_field == "priority":
            matched.sort(key=lambda x: _priority_order.get(x.get("priority", "medium"), 2))
        elif sort_field == "due_date":
            matched.sort(key=lambda x: (x.get("due_date") is None, x.get("due_date")))
        elif sort_field == "duration_min":
            matched.sort(key=lambda x: (x.get("duration_min") is None, x.get("duration_min", 999)))

        elapsed_ms = (time.monotonic() - t_start) * 1000
        return SmartListExecuteResponse(
            smart_list_id=smart_list_id,
            total_matched=len(matched),
            items=matched,
            execution_time_ms=round(elapsed_ms, 2),
        )

    def get_presets(self) -> list[SmartListPresetItem]:
        return _PRESET_SMART_LISTS

    def execute_filter(self, filter_expr: list[dict], items: list[dict]) -> list[dict]:
        """Evaluate RPN filter expression against a list of item dicts."""
        if not filter_expr:
            return items

        stack: list[Any] = []
        for token in filter_expr:
            tok_type = token.get("type")
            if tok_type == "field":
                field = token.get("field", "")
                op = token.get("op", "eq")
                value = token.get("value")
                # Push a partial result: list of items passing this field test
                result = [item for item in items if self._eval_field(item, field, op, value)]
                stack.append(result)
            elif tok_type == "logic":
                op = token.get("op", "AND")
                if len(stack) < 2:
                    continue
                right = stack.pop()
                left = stack.pop()
                if op == "AND":
                    # Intersection by id
                    right_ids = {i.get("id") for i in right}
                    merged = [i for i in left if i.get("id") in right_ids]
                elif op == "OR":
                    # Union by id
                    seen: set[str] = set()
                    merged = []
                    for i in left + right:
                        iid = i.get("id")
                        if iid not in seen:
                            seen.add(iid)
                            merged.append(i)
                elif op == "NOT":
                    right_ids = {i.get("id") for i in right}
                    merged = [i for i in left if i.get("id") not in right_ids]
                else:
                    merged = left
                stack.append(merged)

        if stack:
            return stack[-1]
        return []

    def _eval_field(self, item: dict, field: str, op: str, value: Any) -> bool:
        today = date.today()
        item_val = item.get(field)

        if op == "eq":
            return item_val == value
        if op == "neq":
            return item_val != value
        if op == "in":
            return item_val in (value or [])
        if op == "not_in":
            return item_val not in (value or [])
        if op == "gt":
            return item_val is not None and item_val > value
        if op == "gte":
            return item_val is not None and item_val >= value
        if op == "lt":
            return item_val is not None and item_val < value
        if op == "lte":
            return item_val is not None and item_val <= value
        if op == "contains":
            if isinstance(item_val, list):
                return value in item_val
            if isinstance(item_val, str):
                return value in item_val
            return False
        if op == "within_days":
            if item_val is None:
                return False
            # item_val should be a date string or date
            try:
                if isinstance(item_val, str):
                    item_date = date.fromisoformat(item_val)
                else:
                    item_date = item_val
                delta = (item_date - today).days
                return delta <= int(value)
            except (ValueError, TypeError):
                return False
        return False

    def _validate_filter_expr(self, filter_expr: list[dict]) -> None:
        for token in filter_expr:
            tok_type = token.get("type")
            if tok_type == "field":
                field = token.get("field", "")
                if field not in _ALLOWED_FIELDS:
                    raise BadRequestError(
                        f"Unknown filter field: '{field}'. Allowed: {sorted(_ALLOWED_FIELDS)}",
                        code="dailyos.smart_list_invalid_field",
                    )
                op = token.get("op", "")
                if op not in _FIELD_OPS:
                    raise BadRequestError(
                        f"Unknown filter op: '{op}'. Allowed: {sorted(_FIELD_OPS)}",
                        code="dailyos.smart_list_invalid_op",
                    )
            elif tok_type == "logic":
                op = token.get("op", "")
                if op not in {"AND", "OR", "NOT"}:
                    raise BadRequestError(
                        f"Unknown logic op: '{op}'",
                        code="dailyos.smart_list_invalid_logic",
                    )
            else:
                raise BadRequestError(
                    f"Unknown token type: '{tok_type}'",
                    code="dailyos.smart_list_invalid_token",
                )

    def _backlog_to_dict(self, item: BacklogItem) -> dict:
        return {
            "id": item.id,
            "title": item.title,
            "funnel_layer": item.funnel_layer,
            "priority": item.priority,
            "labels": item.labels,
            "energy_level": item.energy_level,
            "duration_min": item.duration_min,
            "cognitive_cost": item.cognitive_cost,
            "do_date": str(item.do_date) if item.do_date else None,
            "due_date": str(item.due_date) if item.due_date else None,
            "start_date": str(item.start_date) if item.start_date else None,
            "is_frog": item.is_frog,
            "defer_count": item.defer_count,
            "source_module": item.source_module,
            "reward_points": item.reward_points,
        }

    async def _get_by_slug(self, db: AsyncSession, space_id: str, slug: str) -> SmartList | None:
        stmt = select(SmartList).where(
            SmartList.space_id == space_id,
            SmartList.slug == slug,
            SmartList.deleted_at.is_(None),
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    def _to_response(self, sl: SmartList) -> SmartListResponse:
        return SmartListResponse(
            id=sl.id,
            space_id=sl.space_id,
            created_by=sl.created_by,
            created_at=sl.created_at,
            updated_at=sl.updated_at,
            slug=sl.slug,
            name=sl.name,
            name_zh=sl.name_zh,
            description=sl.description,
            icon=sl.icon,
            color=sl.color,
            filter_expr=sl.filter_expr,
            sort_by=sl.sort_by,
            group_by=sl.group_by,
            is_preset=sl.is_preset,
            source_modules=sl.source_modules,
            tags=sl.tags,
            deleted_at=sl.deleted_at,
        )


# ======================== P2e: Guided Daily Ritual Service ========================

_MORNING_CHECKLIST: list[dict] = [
    {
        "key": "review_yesterday",
        "label": "Review yesterday's completion",
        "label_zh": "回顧昨日完成情況",
        "optional": False,
    },
    {
        "key": "check_calendar",
        "label": "Check today's calendar & fixed events",
        "label_zh": "確認今日行程與固定事件",
        "optional": False,
    },
    {
        "key": "set_flight_mode",
        "label": "Set today's flight mode",
        "label_zh": "設定今日飛行模式",
        "optional": False,
    },
    {
        "key": "select_frogs",
        "label": "Identify today's frogs (hardest tasks)",
        "label_zh": "選定今日青蛙任務",
        "optional": False,
    },
    {
        "key": "check_active_workflow",
        "label": "Confirm active workflow",
        "label_zh": "確認當前工作流程",
        "optional": True,
    },
    {
        "key": "set_time_budget",
        "label": "Set time and fuel budget",
        "label_zh": "設定時間與燃料預算",
        "optional": True,
    },
]

_EVENING_CHECKLIST: list[dict] = [
    {
        "key": "mark_completions",
        "label": "Mark task completions",
        "label_zh": "標記任務完成",
        "optional": False,
    },
    {
        "key": "capture_carry_forward",
        "label": "Capture unfinished tasks for tomorrow",
        "label_zh": "捕捉未完成任務延後明日",
        "optional": False,
    },
    {
        "key": "log_reflection",
        "label": "Write daily reflection",
        "label_zh": "寫下每日反思",
        "optional": True,
    },
    {
        "key": "save_black_box",
        "label": "Save pilot black box (end-of-day snapshot)",
        "label_zh": "儲存領航黑盒子",
        "optional": True,
    },
    {
        "key": "rate_workflow",
        "label": "Rate today's workflow",
        "label_zh": "評分今日工作流程",
        "optional": True,
    },
]


class RitualService:
    """Guided daily ritual — morning + evening structured routines."""

    async def morning_ritual(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None = None,
    ) -> MorningRitualResponse:
        today = date.today()

        # Get or create pilot state for today
        pilot_state = await pilot_service.get_or_create_today(db, space_id, user_id=user_id)

        # Get active workflow if any
        stmt_wf = select(Workflow).where(
            Workflow.space_id == space_id,
            Workflow.is_active.is_(True),
            Workflow.deleted_at.is_(None),
        )
        active_wf = (await db.execute(stmt_wf)).scalar_one_or_none()

        # Get unfinished items from yesterday

        yesterday = date.fromordinal(today.toordinal() - 1)
        stmt_yesterday = (
            select(DailyPlan)
            .where(
                DailyPlan.space_id == space_id,
                DailyPlan.plan_date == yesterday,
                DailyPlan.deleted_at.is_(None),
            )
            .limit(1)
        )
        yesterday_plan = (await db.execute(stmt_yesterday)).scalar_one_or_none()

        suggestions: list[str] = []
        if yesterday_plan:
            done_count = sum(1 for i in yesterday_plan.items if i.get("status") == "done")
            total = len(yesterday_plan.items)
            if total > 0:
                pct = round(done_count / total * 100)
                suggestions.append(f"昨日完成率 {pct}%（{done_count}/{total} 項任務）")

        if pilot_state.flight_mode == "emergency":
            suggestions.append("今日為緊急模式 — 僅執行關鍵任務")
        elif pilot_state.flight_mode == "glide":
            suggestions.append("今日為滑翔模式 — 低能量日，優先完成小任務")

        checklist = [
            RitualChecklistItem(
                key=item["key"],
                label=item["label"],
                label_zh=item.get("label_zh"),
                completed=False,
                optional=item.get("optional", False),
            )
            for item in _MORNING_CHECKLIST
        ]

        # Mark active_workflow step as N/A if no active workflow
        if not active_wf:
            for ci in checklist:
                if ci.key == "check_active_workflow":
                    ci.completed = True  # auto-pass if not applicable

        return MorningRitualResponse(
            plan_date=today,
            checklist=checklist,
            suggestions=suggestions,
            pilot_state=pilot_service._to_response(pilot_state),
            active_workflow=workflow_service._to_response(active_wf) if active_wf else None,
        )

    async def evening_ritual(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None = None,
    ) -> EveningRitualResponse:
        today = date.today()

        # Get today's plan
        stmt_plan = select(DailyPlan).where(
            DailyPlan.space_id == space_id,
            DailyPlan.plan_date == today,
            DailyPlan.deleted_at.is_(None),
        )
        plan = (await db.execute(stmt_plan)).scalar_one_or_none()

        review_data: dict = {"plan_date": str(today)}
        carry_forward: list[dict] = []

        if plan:
            done_items = [i for i in plan.items if i.get("status") == "done"]
            pending_items = [i for i in plan.items if i.get("status") != "done"]
            review_data.update(
                {
                    "total_items": len(plan.items),
                    "done_count": len(done_items),
                    "pending_count": len(pending_items),
                    "completion_score": plan.completion_score,
                    "status": plan.status,
                }
            )
            carry_forward = [
                {
                    "title": i.get("title", ""),
                    "source": "daily_plan",
                    "original_status": i.get("status"),
                }
                for i in pending_items
            ]

        # Get pilot state for black box
        stmt_ps = select(PilotState).where(
            PilotState.space_id == space_id,
            PilotState.state_date == today,
            PilotState.deleted_at.is_(None),
        )
        pilot_state = (await db.execute(stmt_ps)).scalar_one_or_none()
        pilot_summary = None
        if pilot_state:
            pilot_summary = {
                "flight_mode": pilot_state.flight_mode,
                "fuel_spent": pilot_state.cognitive_fuel_spent,
                "fuel_budget": pilot_state.cognitive_fuel_budget,
                "time_spent_min": pilot_state.time_spent_min,
                "decision_count": pilot_state.decision_count,
                "verify_level": pilot_state.verify_level,
            }

        checklist = [
            RitualChecklistItem(
                key=item["key"],
                label=item["label"],
                label_zh=item.get("label_zh"),
                completed=False,
                optional=item.get("optional", False),
            )
            for item in _EVENING_CHECKLIST
        ]

        return EveningRitualResponse(
            plan_date=today,
            checklist=checklist,
            review_data=review_data,
            carry_forward=carry_forward,
            pilot_summary=pilot_summary,
        )

    async def get_ritual_status(
        self,
        db: AsyncSession,
        space_id: str,
    ) -> RitualStatusResponse:
        today = date.today()

        # Check method_state in today's plan for ritual completion markers
        stmt_plan = select(DailyPlan).where(
            DailyPlan.space_id == space_id,
            DailyPlan.plan_date == today,
            DailyPlan.deleted_at.is_(None),
        )
        plan = (await db.execute(stmt_plan)).scalar_one_or_none()

        morning_completed = False
        morning_completed_at = None
        evening_completed = False
        evening_completed_at = None

        if plan and plan.method_state:
            ritual_state = plan.method_state.get("ritual", {})
            morning_completed = ritual_state.get("morning_completed", False)
            if morning_ts := ritual_state.get("morning_completed_at"):
                try:
                    morning_completed_at = datetime.fromisoformat(morning_ts)
                except (ValueError, TypeError):
                    pass
            evening_completed = ritual_state.get("evening_completed", False)
            if evening_ts := ritual_state.get("evening_completed_at"):
                try:
                    evening_completed_at = datetime.fromisoformat(evening_ts)
                except (ValueError, TypeError):
                    pass

        morning_checklist = [
            RitualChecklistItem(
                key=item["key"],
                label=item["label"],
                label_zh=item.get("label_zh"),
                completed=morning_completed,
                optional=item.get("optional", False),
            )
            for item in _MORNING_CHECKLIST
        ]
        evening_checklist = [
            RitualChecklistItem(
                key=item["key"],
                label=item["label"],
                label_zh=item.get("label_zh"),
                completed=evening_completed,
                optional=item.get("optional", False),
            )
            for item in _EVENING_CHECKLIST
        ]

        return RitualStatusResponse(
            plan_date=today,
            morning_completed=morning_completed,
            morning_completed_at=morning_completed_at,
            evening_completed=evening_completed,
            evening_completed_at=evening_completed_at,
            morning_checklist=morning_checklist,
            evening_checklist=evening_checklist,
        )

    async def complete_morning_ritual(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None = None,
    ) -> RitualStatusResponse:
        """Mark today's morning ritual as completed.

        Step 6 audit finding: ritual state was previously read by
        get_ritual_status but never written. This method (and its evening
        counterpart) are the missing write side.
        """
        await self._mark_ritual_complete(db, space_id, "morning", user_id=user_id)
        return await self.get_ritual_status(db, space_id)

    async def complete_evening_ritual(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None = None,
    ) -> RitualStatusResponse:
        """Mark today's evening ritual as completed."""
        await self._mark_ritual_complete(db, space_id, "evening", user_id=user_id)
        return await self.get_ritual_status(db, space_id)

    async def _mark_ritual_complete(
        self,
        db: AsyncSession,
        space_id: str,
        slot: str,
        user_id: str | None = None,
    ) -> None:
        """Write ritual completion marker into today's DailyPlan.method_state."""
        if slot not in ("morning", "evening"):
            raise BadRequestError(
                f"Invalid ritual slot: {slot}", code="dailyos.invalid_ritual_slot"
            )

        # Lazy import — daily_plan_service lives in services.py and importing it
        # at module top creates a circular dep with this file.
        from .services import daily_plan_service

        plan = await daily_plan_service.get_or_create_today(db, space_id, user_id=user_id)
        method_state = dict(plan.method_state or {})
        ritual_state = dict(method_state.get("ritual", {}))

        now_iso = datetime.now(UTC).isoformat()
        if slot == "morning":
            ritual_state["morning_completed"] = True
            ritual_state["morning_completed_at"] = now_iso
        else:
            ritual_state["evening_completed"] = True
            ritual_state["evening_completed_at"] = now_iso

        method_state["ritual"] = ritual_state
        plan.method_state = method_state
        plan.updated_at = datetime.now(UTC)
        await db.flush()


# ======================== Singletons ========================

workflow_service = WorkflowService()
pilot_service = PilotService()
snippet_service = SnippetService()
smart_list_service = SmartListService()
ritual_service = RitualService()

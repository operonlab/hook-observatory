"""Daily OS P3+P4 service layer.

Features: Eisenhower, Wizard, Templates, Gamification, Onboarding, Experiments.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.errors import BadRequestError, NotFoundError
from src.shared.models import _uuid7_hex
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService

from .models import (
    BacklogItem,
    DailyPlan,
    Experiment,
    GamificationState,
    PlanTemplate,
    PointHistory,
    SmartList,
)
from .schemas_p3 import (
    AwardPointsResponse,
    EisenhowerQuadrant,
    EisenhowerResponse,
    ExperimentCreate,
    ExperimentResponse,
    ExperimentResultsResponse,
    ExperimentUpdate,
    GamificationStateResponse,
    InterventionsResponse,
    InterventionType,
    OnboardingResult,
    OnboardingSubmitRequest,
    PlanTemplateCreate,
    PlanTemplateResponse,
    PlanTemplateUpdate,
    PointHistoryResponse,
    QuizOption,
    QuizQuestion,
    QuizResponse,
    StreakResponse,
    TemplateApplyResponse,
    WizardQuestion,
    WizardResult,
    WizardStepResponse,
)

logger = logging.getLogger(__name__)

# ======================== P3a: Eisenhower Service ========================

_EISENHOWER_SLUGS = {
    "q1": "eisenhower-q1-do-first",
    "q2": "eisenhower-q2-schedule",
    "q3": "eisenhower-q3-delegate",
    "q4": "eisenhower-q4-eliminate",
}

_EISENHOWER_PRESETS: list[dict[str, Any]] = [
    {
        "slug": _EISENHOWER_SLUGS["q1"],
        "name": "Do First",
        "name_zh": "立即執行",
        "description": "Urgent + High Priority, due within 2 days",
        "icon": "🔥",
        "color": "#f38ba8",
        "filter_expr": [
            {"type": "field", "field": "priority", "op": "in", "value": ["urgent", "high"]},
            {"type": "field", "field": "due_within_days", "op": "lte", "value": 2},
            {"type": "op", "op": "AND"},
        ],
        "sort_by": "due_date",
        "is_preset": True,
        "tags": ["eisenhower", "q1"],
    },
    {
        "slug": _EISENHOWER_SLUGS["q2"],
        "name": "Schedule",
        "name_zh": "計劃安排",
        "description": "High Priority, no immediate deadline",
        "icon": "📅",
        "color": "#a6e3a1",
        "filter_expr": [
            {"type": "field", "field": "priority", "op": "in", "value": ["urgent", "high"]},
            {"type": "field", "field": "due_within_days", "op": "gt", "value": 2},
            {"type": "op", "op": "AND"},
        ],
        "sort_by": "priority",
        "is_preset": True,
        "tags": ["eisenhower", "q2"],
    },
    {
        "slug": _EISENHOWER_SLUGS["q3"],
        "name": "Delegate",
        "name_zh": "委派他人",
        "description": "Urgent but lower priority",
        "icon": "🤝",
        "color": "#fab387",
        "filter_expr": [
            {"type": "field", "field": "due_within_days", "op": "lte", "value": 2},
            {"type": "field", "field": "priority", "op": "in", "value": ["medium", "low"]},
            {"type": "op", "op": "AND"},
        ],
        "sort_by": "due_date",
        "is_preset": True,
        "tags": ["eisenhower", "q3"],
    },
    {
        "slug": _EISENHOWER_SLUGS["q4"],
        "name": "Eliminate",
        "name_zh": "排除刪除",
        "description": "Not urgent, not important",
        "icon": "🗑️",
        "color": "#6c7086",
        "filter_expr": [
            {"type": "field", "field": "priority", "op": "in", "value": ["medium", "low"]},
            {"type": "field", "field": "due_within_days", "op": "gt", "value": 2},
            {"type": "op", "op": "AND"},
        ],
        "sort_by": "created_at",
        "is_preset": True,
        "tags": ["eisenhower", "q4"],
    },
]


class EisenhowerService:
    """Eisenhower matrix — 4-quadrant view backed by SmartList presets."""

    async def ensure_smart_lists(self, db: AsyncSession, space_id: str) -> None:
        """Seed the 4 Eisenhower SmartList presets if they don't exist yet."""
        for preset in _EISENHOWER_PRESETS:
            existing = await db.execute(
                select(SmartList).where(
                    SmartList.space_id == space_id,
                    SmartList.slug == preset["slug"],
                    SmartList.deleted_at.is_(None),
                )
            )
            if existing.scalars().first() is None:
                obj = SmartList(
                    id=_uuid7_hex(),
                    space_id=space_id,
                    **preset,
                )
                db.add(obj)
        await db.flush()

    def _classify_item(self, item: dict, today: date) -> str:
        """Classify a backlog item into an Eisenhower quadrant key."""
        priority = item.get("priority", "medium")
        due_date_raw = item.get("due_date")
        is_high = priority in ("urgent", "high")

        due_within_2 = False
        if due_date_raw:
            try:
                due = (
                    date.fromisoformat(due_date_raw)
                    if isinstance(due_date_raw, str)
                    else due_date_raw
                )
                due_within_2 = (due - today).days <= 2
            except (ValueError, TypeError):
                pass

        if is_high and due_within_2:
            return "q1"
        if is_high and not due_within_2:
            return "q2"
        if not is_high and due_within_2:
            return "q3"
        return "q4"

    async def get_quadrants(self, db: AsyncSession, space_id: str) -> EisenhowerResponse:
        """Return 4-quadrant view from backlog items."""
        await self.ensure_smart_lists(db, space_id)

        stmt = select(BacklogItem).where(
            BacklogItem.space_id == space_id,
            BacklogItem.deleted_at.is_(None),
            BacklogItem.funnel_layer.in_(["ready", "master", "scheduled"]),
        )
        rows: Sequence[BacklogItem] = (await db.execute(stmt)).scalars().all()

        today = date.today()
        buckets: dict[str, list[dict]] = {"q1": [], "q2": [], "q3": [], "q4": []}

        for item in rows:
            item_dict = {
                "id": item.id,
                "title": item.title,
                "priority": item.priority,
                "due_date": item.due_date.isoformat() if item.due_date else None,
                "funnel_layer": item.funnel_layer,
                "energy_level": item.energy_level,
                "duration_min": item.duration_min,
                "defer_count": item.defer_count,
                "is_frog": item.is_frog,
            }
            q = self._classify_item(item_dict, today)
            buckets[q].append(item_dict)

        labels = {
            "q1": ("Do First", "🔥 Urgent + Important — act now"),
            "q2": ("Schedule", "📅 Important, not urgent — plan it"),
            "q3": ("Delegate", "🤝 Urgent, not important — hand off"),
            "q4": ("Eliminate", "🗑️ Not urgent, not important — drop it"),
        }

        quadrants = {}
        for key in ("q1", "q2", "q3", "q4"):
            name, desc = labels[key]
            quadrants[key] = EisenhowerQuadrant(
                quadrant=key,  # type: ignore[arg-type]
                label=name,
                description=desc,
                items=buckets[key],
                item_count=len(buckets[key]),
            )

        total = sum(len(v) for v in buckets.values())
        return EisenhowerResponse(
            q1=quadrants["q1"],
            q2=quadrants["q2"],
            q3=quadrants["q3"],
            q4=quadrants["q4"],
            total_items=total,
        )


# ======================== P3b: Procrastination Wizard ========================

_WIZARD_STEPS: list[dict[str, Any]] = [
    {
        "step": 1,
        "question": "Why are you avoiding this task?",
        "hint": "Be honest — unclear outcome, fear of failure, overwhelm, boredom?",
    },
    {
        "step": 2,
        "question": "What's the absolute smallest first step you could take right now?",
        "hint": "Think 2-minute actions: open the file, write one sentence, make one call.",
    },
    {
        "step": 3,
        "question": "What would make this task easier or more enjoyable?",
        "hint": "Different time of day, better tools, background music, a partner?",
    },
    {
        "step": 4,
        "question": "Can you commit to just 5 minutes on this task right now?",
        "hint": "Just starting is often the hardest part. 5 minutes is enough.",
    },
]

_INTERVENTION_TYPES: list[dict[str, Any]] = [
    {
        "id": "procrastination_wizard",
        "name": "Procrastination Wizard",
        "description": "4-step guided intervention to break through avoidance and resistance",
        "steps": 4,
    },
    {
        "id": "two_minute_rule",
        "name": "Two-Minute Rule",
        "description": "If it takes less than 2 minutes, do it now",
        "steps": 1,
    },
    {
        "id": "body_double",
        "name": "Body Double",
        "description": "Work alongside someone else (real or virtual) to stay focused",
        "steps": 1,
    },
]


class ProcrastinationWizardService:
    """Stateless wizard — state carried in request/response payload."""

    def start(self, item_id: str) -> WizardStepResponse:
        step_data = _WIZARD_STEPS[0]
        return WizardStepResponse(
            completed=False,
            question=WizardQuestion(
                step=1,
                total_steps=len(_WIZARD_STEPS),
                question=step_data["question"],
                hint=step_data.get("hint"),
                session_state={"item_id": item_id, "answers": {}},
            ),
        )

    def respond(
        self,
        item_id: str,
        step: int,
        answer: str,
        session_state: dict,
    ) -> WizardStepResponse:
        # Record the answer
        answers: dict[str, str] = dict(session_state.get("answers", {}))
        answers[str(step)] = answer

        next_step = step + 1

        if next_step > len(_WIZARD_STEPS):
            # All steps done — produce recommendation
            recommendation, micro_task, reasoning = self._recommend(answers, answer)
            return WizardStepResponse(
                completed=True,
                result=WizardResult(
                    completed=True,
                    recommendation=recommendation,
                    micro_task=micro_task,
                    original_item_id=item_id,
                    reasoning=reasoning,
                ),
            )

        step_data = _WIZARD_STEPS[next_step - 1]
        new_state = {"item_id": item_id, "answers": answers}
        return WizardStepResponse(
            completed=False,
            question=WizardQuestion(
                step=next_step,
                total_steps=len(_WIZARD_STEPS),
                question=step_data["question"],
                hint=step_data.get("hint"),
                session_state=new_state,
            ),
        )

    def _recommend(self, answers: dict[str, str], last_answer: str) -> tuple[str, str, str]:
        """Derive recommendation from wizard answers."""
        # Step 1 blocker analysis
        blocker = answers.get("1", "").lower()
        step2 = answers.get("2", "")

        if any(w in blocker for w in ("unclear", "confused", "don't know", "complex")):
            return (
                "decompose",
                step2 or "Break it into 3 smaller sub-tasks",
                "Task clarity is blocking you — decompose into smaller, concrete steps",
            )
        if any(w in blocker for w in ("boring", "hate", "dislike", "unimportant")):
            return (
                "delegate",
                "Identify someone who can take this on",
                "Low motivation suggests this may not be the best use of your energy",
            )
        if any(w in blocker for w in ("busy", "later", "deadline", "not now")):
            return (
                "defer",
                "Schedule a specific time slot in the next 48 hours",
                "Timing is the blocker — commit to a concrete future slot",
            )
        # Default: micro-start
        return (
            "do_now",
            step2 or "Open the task and work on it for 5 minutes",
            "You have everything you need — just start for 5 minutes",
        )

    def get_interventions(self) -> InterventionsResponse:
        return InterventionsResponse(
            interventions=[InterventionType(**t) for t in _INTERVENTION_TYPES]
        )


# ======================== P3c: Template Service ========================


class TemplateService(
    BaseCRUDService[PlanTemplate, PlanTemplateCreate, PlanTemplateUpdate, PlanTemplateResponse]
):
    model = PlanTemplate
    audit_module = "dailyos"
    audit_entity_type = "plan_templates"

    def to_response(self, instance: PlanTemplate) -> PlanTemplateResponse:  # type: ignore[override]
        return PlanTemplateResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            slug=instance.slug,
            name=instance.name,
            name_zh=instance.name_zh,
            description=instance.description,
            items=instance.items or [],
            method_ids=instance.method_ids,
            toggle_overrides=instance.toggle_overrides,
            tags=instance.tags,
            use_count=instance.use_count,
            last_used_at=instance.last_used_at,
            deleted_at=instance.deleted_at,
        )

    async def list_templates(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams,
    ) -> PaginatedResponse[PlanTemplateResponse]:
        return await self.list(db, space_id, pagination)

    async def create_from_plan(
        self,
        db: AsyncSession,
        plan_id: str,
        space_id: str,
        slug: str,
        name: str,
        name_zh: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        user_id: str | None = None,
    ) -> PlanTemplate:
        """Snapshot an existing daily plan into a reusable template."""
        stmt = select(DailyPlan).where(
            DailyPlan.id == plan_id,
            DailyPlan.space_id == space_id,
            DailyPlan.deleted_at.is_(None),
        )
        plan = (await db.execute(stmt)).scalars().first()
        if plan is None:
            raise NotFoundError("Daily plan not found", code="dailyos.plan_not_found")

        data = PlanTemplateCreate(
            slug=slug,
            name=name,
            name_zh=name_zh,
            description=description,
            items=list(plan.items or []),
            tags=tags,
        )
        return await self.create(db, space_id, data, user_id=user_id)

    async def apply_template(
        self,
        db: AsyncSession,
        template_id: str,
        space_id: str,
        plan_date: date | None = None,
        context: str = "default",
        merge_mode: str = "append",
        user_id: str | None = None,
    ) -> TemplateApplyResponse:
        """Apply template to today's (or specified date's) daily plan."""
        template = await self.get(db, template_id)
        if template is None or template.space_id != space_id:
            raise NotFoundError("Template not found", code="dailyos.template_not_found")

        target_date = plan_date or date.today()

        # Get or create plan for target date
        stmt = select(DailyPlan).where(
            DailyPlan.space_id == space_id,
            DailyPlan.plan_date == target_date,
            DailyPlan.context == context,
            DailyPlan.deleted_at.is_(None),
        )
        plan = (await db.execute(stmt)).scalars().first()
        if plan is None:
            plan = DailyPlan(
                id=_uuid7_hex(),
                space_id=space_id,
                plan_date=target_date,
                context=context,
                status="planning",
                items=[],
                created_by=user_id,
            )
            db.add(plan)
            await db.flush()

        template_items = list(template.items or [])
        existing_items = list(plan.items or [])

        if merge_mode == "replace":
            new_items = template_items
        else:
            # append — assign new IDs to avoid collisions
            new_template_items = []
            for item in template_items:
                item_copy = dict(item)
                item_copy["id"] = _uuid7_hex()
                item_copy["status"] = "pending"
                new_template_items.append(item_copy)
            new_items = existing_items + new_template_items

        plan.items = new_items  # type: ignore[assignment]
        items_added = len(template_items)

        # Update template usage stats
        template.use_count = (template.use_count or 0) + 1
        template.last_used_at = datetime.now(UTC)
        await db.flush()

        return TemplateApplyResponse(
            plan_id=plan.id,
            plan_date=target_date,
            items_added=items_added,
            total_items=len(new_items),
        )


# ======================== P3d: Gamification Service ========================

_LEVEL_THRESHOLDS = [0, 100, 300, 600, 1000, 1500, 2100, 2800, 3600, 4500, 5500]

_ACHIEVEMENT_DEFINITIONS = [
    {
        "id": "streak_7",
        "name": "Week Warrior",
        "description": "7-day streak",
        "condition": "streak_7",
    },
    {
        "id": "streak_30",
        "name": "Monthly Master",
        "description": "30-day streak",
        "condition": "streak_30",
    },
    {
        "id": "points_100",
        "name": "Century Club",
        "description": "100 total points",
        "condition": "points_100",
    },
    {
        "id": "points_1000",
        "name": "Millionaire Mindset",
        "description": "1,000 total points",
        "condition": "points_1000",
    },
    {
        "id": "points_5000",
        "name": "Elite Performer",
        "description": "5,000 total points",
        "condition": "points_5000",
    },
    {"id": "streak_3", "name": "Hat Trick", "description": "3-day streak", "condition": "streak_3"},
]


def _compute_level(total_points: int) -> int:
    level = 1
    for i, threshold in enumerate(_LEVEL_THRESHOLDS):
        if total_points >= threshold:
            level = i + 1
    return min(level, len(_LEVEL_THRESHOLDS))


class GamificationService:
    """Gamification state management — points, streaks, levels, achievements."""

    async def _get_or_create_state(
        self, db: AsyncSession, space_id: str, user_id: str | None = None
    ) -> GamificationState:
        stmt = select(GamificationState).where(
            GamificationState.space_id == space_id,
            GamificationState.deleted_at.is_(None),
        )
        state = (await db.execute(stmt)).scalars().first()
        if state is None:
            state = GamificationState(
                id=_uuid7_hex(),
                space_id=space_id,
                created_by=user_id,
                total_points=0,
                current_streak=0,
                longest_streak=0,
                level=1,
                achievements=[],
            )
            db.add(state)
            await db.flush()
        return state

    def _to_response(self, state: GamificationState) -> GamificationStateResponse:
        return GamificationStateResponse(
            id=state.id,
            space_id=state.space_id,
            created_by=state.created_by,
            created_at=state.created_at,
            updated_at=state.updated_at,
            total_points=state.total_points,
            current_streak=state.current_streak,
            longest_streak=state.longest_streak,
            last_streak_date=state.last_streak_date,
            level=state.level,
            achievements=list(state.achievements or []),
            reward_config=state.reward_config,
        )

    async def get_state(self, db: AsyncSession, space_id: str) -> GamificationStateResponse:
        state = await self._get_or_create_state(db, space_id)
        return self._to_response(state)

    async def award_points(
        self,
        db: AsyncSession,
        space_id: str,
        points: int,
        reason: str,
        source_type: str,
        source_id: str | None = None,
        multiplier: float = 1.0,
        defer_count: int = 0,
        user_id: str | None = None,
    ) -> AwardPointsResponse:
        state = await self._get_or_create_state(db, space_id, user_id)

        # Dynamic multiplier based on defer count
        if defer_count > 0:
            dynamic_mult = min(1.0 + defer_count * 0.5, 3.0)
            multiplier = max(multiplier, dynamic_mult)

        effective_points = round(points * multiplier)

        # Create PointHistory entry
        history_entry = PointHistory(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id,
            points=effective_points,
            reason=reason,
            source_type=source_type,
            source_id=source_id,
            multiplier=multiplier,
        )
        db.add(history_entry)

        # Update state
        state.total_points = (state.total_points or 0) + effective_points
        new_level = _compute_level(state.total_points)
        state.level = new_level

        # Check achievements
        new_achievements = self.check_achievements(state)
        if new_achievements:
            existing_ids = {a["id"] for a in (state.achievements or [])}
            current = list(state.achievements or [])
            for ach in new_achievements:
                if ach["id"] not in existing_ids:
                    current.append(ach)
            state.achievements = current

        await db.flush()

        return AwardPointsResponse(
            points_awarded=points,
            effective_points=effective_points,
            multiplier=multiplier,
            new_total=state.total_points,
            new_level=new_level,
            new_achievements=new_achievements,
        )

    async def update_streak(
        self, db: AsyncSession, space_id: str, plan_date: date, user_id: str | None = None
    ) -> GamificationStateResponse:
        state = await self._get_or_create_state(db, space_id, user_id)

        yesterday = plan_date - timedelta(days=1)
        last = state.last_streak_date

        if last is None:
            state.current_streak = 1
        elif last == plan_date:
            # Already recorded today — no-op
            pass
        elif last == yesterday:
            state.current_streak = (state.current_streak or 0) + 1
        else:
            # Streak broken
            state.current_streak = 1

        state.last_streak_date = plan_date
        if (state.current_streak or 0) > (state.longest_streak or 0):
            state.longest_streak = state.current_streak

        # Check streak achievements
        new_achievements = self.check_achievements(state)
        if new_achievements:
            existing_ids = {a["id"] for a in (state.achievements or [])}
            current = list(state.achievements or [])
            for ach in new_achievements:
                if ach["id"] not in existing_ids:
                    current.append(ach)
            state.achievements = current

        await db.flush()
        return self._to_response(state)

    def check_achievements(self, state: GamificationState) -> list[dict]:
        """Return list of newly earned achievements not yet in state."""
        earned_ids = {a["id"] for a in (state.achievements or [])}
        new_ach = []
        now_iso = datetime.now(UTC).isoformat()

        conditions: dict[str, bool] = {
            "streak_3": (state.current_streak or 0) >= 3,
            "streak_7": (state.current_streak or 0) >= 7,
            "streak_30": (state.current_streak or 0) >= 30,
            "points_100": (state.total_points or 0) >= 100,
            "points_1000": (state.total_points or 0) >= 1000,
            "points_5000": (state.total_points or 0) >= 5000,
        }

        for defn in _ACHIEVEMENT_DEFINITIONS:
            cond_key = defn["condition"]
            if defn["id"] not in earned_ids and conditions.get(cond_key, False):
                new_ach.append(
                    {
                        "id": defn["id"],
                        "name": defn["name"],
                        "description": defn["description"],
                        "earned_at": now_iso,
                    }
                )

        return new_ach

    async def get_history(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams,
    ) -> PaginatedResponse[PointHistoryResponse]:
        count_q = (
            select(func.count())
            .select_from(PointHistory)
            .where(
                PointHistory.space_id == space_id,
                PointHistory.deleted_at.is_(None),
            )
        )
        total = (await db.execute(count_q)).scalar_one()

        stmt = (
            select(PointHistory)
            .where(
                PointHistory.space_id == space_id,
                PointHistory.deleted_at.is_(None),
            )
            .order_by(PointHistory.earned_at.desc())
            .offset((pagination.page - 1) * pagination.page_size)
            .limit(pagination.page_size)
        )
        rows: Sequence[PointHistory] = (await db.execute(stmt)).scalars().all()

        items = [
            PointHistoryResponse(
                id=r.id,
                space_id=r.space_id,
                created_by=r.created_by,
                created_at=r.created_at,
                updated_at=r.updated_at,
                points=r.points,
                reason=r.reason,
                source_type=r.source_type,
                source_id=r.source_id,
                multiplier=r.multiplier,
                earned_at=r.earned_at,
            )
            for r in rows
        ]
        return PaginatedResponse[PointHistoryResponse](
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
        )

    async def get_streak(self, db: AsyncSession, space_id: str) -> StreakResponse:
        state = await self._get_or_create_state(db, space_id)
        today = date.today()
        is_active = state.last_streak_date == today if state.last_streak_date else False
        return StreakResponse(
            current_streak=state.current_streak or 0,
            longest_streak=state.longest_streak or 0,
            last_streak_date=state.last_streak_date,
            is_active_today=is_active,
        )


# ======================== P3e: Onboarding Quiz Service ========================

_QUIZ_QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "challenge",
        "question": "What's your biggest challenge with daily planning?",
        "multi_select": False,
        "options": [
            {
                "value": "procrastination",
                "label": "I procrastinate on important tasks",
                "tags": ["procrastination", "focus"],
            },
            {
                "value": "overwhelm",
                "label": "I feel overwhelmed by too many tasks",
                "tags": ["overwhelm", "minimal"],
            },
            {
                "value": "focus",
                "label": "I struggle to maintain focus",
                "tags": ["focus", "time-blocking"],
            },
            {
                "value": "time_management",
                "label": "I lose track of time",
                "tags": ["time-management", "time-blocking"],
            },
        ],
    },
    {
        "id": "structure",
        "question": "How structured do you want your day?",
        "multi_select": False,
        "options": [
            {
                "value": "structured",
                "label": "Very structured — I like clear schedules",
                "tags": ["structured", "time-blocking"],
            },
            {
                "value": "flexible",
                "label": "Flexible — I adapt as the day goes",
                "tags": ["flexible", "free-flow"],
            },
            {"value": "mixed", "label": "A bit of both", "tags": ["mixed"]},
        ],
    },
    {
        "id": "time_style",
        "question": "Do you prefer time blocks or free-flow work?",
        "multi_select": False,
        "options": [
            {
                "value": "time_blocking",
                "label": "Time blocks — I schedule specific slots",
                "tags": ["time-blocking"],
            },
            {
                "value": "free_flow",
                "label": "Free-flow — I work when inspired",
                "tags": ["free-flow"],
            },
        ],
    },
    {
        "id": "task_count",
        "question": "How many tasks per day feels comfortable?",
        "multi_select": False,
        "options": [
            {"value": "minimal", "label": "1-3 tasks (focused)", "tags": ["minimal"]},
            {"value": "moderate", "label": "4-7 tasks (balanced)", "tags": ["moderate"]},
            {"value": "ambitious", "label": "8+ tasks (ambitious)", "tags": ["ambitious"]},
        ],
    },
]

_WORKFLOW_TAG_MAP: list[dict[str, Any]] = [
    {
        "slug": "time-blocking-focused",
        "name": "Time Blocking (Focused)",
        "tags": ["time-blocking", "structured", "focus"],
        "recommended_toggles": ["time_blocks", "focus_mode", "do_not_disturb"],
    },
    {
        "slug": "procrastination-buster",
        "name": "Procrastination Buster",
        "tags": ["procrastination", "focus", "minimal"],
        "recommended_toggles": ["wizard_enabled", "frog_first", "micro_tasks"],
    },
    {
        "slug": "flexible-creative",
        "name": "Flexible Creative",
        "tags": ["free-flow", "flexible", "mixed"],
        "recommended_toggles": ["free_flow_mode", "energy_tracking"],
    },
    {
        "slug": "overwhelm-rescue",
        "name": "Overwhelm Rescue",
        "tags": ["overwhelm", "minimal", "structured"],
        "recommended_toggles": ["minimal_mode", "daily_limit_3", "eisenhower_view"],
    },
]


class OnboardingService:
    """Onboarding quiz — tag-matching approach to recommend workflow + toggles."""

    def get_quiz(self) -> QuizResponse:
        questions = []
        for q in _QUIZ_QUESTIONS:
            questions.append(
                QuizQuestion(
                    id=q["id"],
                    question=q["question"],
                    multi_select=q.get("multi_select", False),
                    options=[QuizOption(**opt) for opt in q["options"]],
                )
            )
        return QuizResponse(questions=questions)

    def _collect_tags(self, answers: dict[str, str | list[str]]) -> list[str]:
        """Map answer values to tags via quiz option definitions."""
        # Build a lookup: question_id -> {value -> [tags]}
        q_lookup: dict[str, dict[str, list[str]]] = {}
        for q in _QUIZ_QUESTIONS:
            q_lookup[q["id"]] = {opt["value"]: opt["tags"] for opt in q["options"]}

        tags: list[str] = []
        for qid, answer in answers.items():
            option_map = q_lookup.get(qid, {})
            if isinstance(answer, list):
                for v in answer:
                    tags.extend(option_map.get(v, []))
            else:
                tags.extend(option_map.get(answer, []))
        return tags

    def submit(self, request: OnboardingSubmitRequest) -> OnboardingResult:
        matched_tags = self._collect_tags(request.answers)
        tag_set = set(matched_tags)

        # Score each workflow by tag overlap
        best_workflow = None
        best_score = -1
        for wf in _WORKFLOW_TAG_MAP:
            wf_tags = set(wf["tags"])
            score = len(tag_set & wf_tags)
            if score > best_score:
                best_score = score
                best_workflow = wf

        if best_workflow and best_score > 0:
            return OnboardingResult(
                recommended_workflow_slug=best_workflow["slug"],
                recommended_workflow_name=best_workflow["name"],
                recommended_toggles=best_workflow["recommended_toggles"],
                matched_tags=list(tag_set),
                description=(
                    f"Based on your answers, we recommend the "
                    f"{best_workflow['name']} workflow to help you get started."
                ),
            )

        return OnboardingResult(
            recommended_workflow_slug=None,
            recommended_workflow_name=None,
            recommended_toggles=[],
            matched_tags=list(tag_set),
            description="Start with your default settings and customize as you learn your rhythm.",
        )


# ======================== P4: Experiment Service ========================


class ExperimentService(
    BaseCRUDService[Experiment, ExperimentCreate, ExperimentUpdate, ExperimentResponse]
):
    model = Experiment
    audit_module = "dailyos"
    audit_entity_type = "experiments"

    def to_response(self, instance: Experiment) -> ExperimentResponse:  # type: ignore[override]
        return ExperimentResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            name=instance.name,
            name_zh=instance.name_zh,
            description=instance.description,
            status=instance.status,
            variant_a=instance.variant_a or {},
            variant_b=instance.variant_b or {},
            duration_days=instance.duration_days,
            started_at=instance.started_at,
            ended_at=instance.ended_at,
            results=instance.results,
            winner=instance.winner,
            deleted_at=instance.deleted_at,
        )

    async def list_experiments(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams,
        status: str | None = None,
    ) -> PaginatedResponse[ExperimentResponse]:
        base_where = [
            Experiment.space_id == space_id,
            Experiment.deleted_at.is_(None),
        ]
        if status:
            base_where.append(Experiment.status == status)

        count_q = select(func.count()).select_from(Experiment).where(*base_where)
        total = (await db.execute(count_q)).scalar_one()

        stmt = (
            select(Experiment)
            .where(*base_where)
            .order_by(Experiment.created_at.desc())
            .offset((pagination.page - 1) * pagination.page_size)
            .limit(pagination.page_size)
        )
        rows: Sequence[Experiment] = (await db.execute(stmt)).scalars().all()
        return PaginatedResponse[ExperimentResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
        )

    async def start_experiment(
        self, db: AsyncSession, experiment_id: str, space_id: str
    ) -> ExperimentResponse:
        exp = await self.get(db, experiment_id)
        if exp is None or exp.space_id != space_id:
            raise NotFoundError("Experiment not found", code="dailyos.experiment_not_found")
        if exp.status != "draft":
            raise BadRequestError(
                f"Cannot start experiment in status '{exp.status}'",
                code="dailyos.experiment_bad_status",
            )
        exp.status = "running"
        exp.started_at = datetime.now(UTC)
        await db.flush()
        return self.to_response(exp)

    async def end_experiment(
        self, db: AsyncSession, experiment_id: str, space_id: str
    ) -> ExperimentResponse:
        exp = await self.get(db, experiment_id)
        if exp is None or exp.space_id != space_id:
            raise NotFoundError("Experiment not found", code="dailyos.experiment_not_found")
        if exp.status != "running":
            raise BadRequestError(
                f"Cannot end experiment in status '{exp.status}'",
                code="dailyos.experiment_bad_status",
            )

        now = datetime.now(UTC)
        exp.status = "completed"
        exp.ended_at = now

        # Compute results from DailyPlan data within experiment window
        if exp.started_at:
            results, winner = await self._compute_results(db, exp)
            exp.results = results
            exp.winner = winner
        else:
            exp.results = {}
            exp.winner = "inconclusive"

        await db.flush()
        return self.to_response(exp)

    async def _compute_results(self, db: AsyncSession, exp: Experiment) -> tuple[dict, str]:
        """Compare variant_a vs variant_b based on plan metrics during experiment period."""
        start = exp.started_at
        end = exp.ended_at or datetime.now(UTC)

        start_date = start.date() if start else date.today()
        end_date = end.date()

        # Gather plans in the experiment window
        stmt = select(DailyPlan).where(
            DailyPlan.space_id == exp.space_id,
            DailyPlan.plan_date >= start_date,
            DailyPlan.plan_date <= end_date,
            DailyPlan.deleted_at.is_(None),
        )
        plans: Sequence[DailyPlan] = (await db.execute(stmt)).scalars().all()

        # Split plans into A/B halves by date order (simple alternating assignment)
        sorted_plans = sorted(plans, key=lambda p: p.plan_date)
        a_plans = sorted_plans[::2]
        b_plans = sorted_plans[1::2]

        def _stats(plan_list: Sequence[DailyPlan]) -> dict:
            if not plan_list:
                return {"count": 0, "avg_completion_score": 0.0, "total_items": 0}
            scores = [p.completion_score for p in plan_list if p.completion_score is not None]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            total_items = sum(len(p.items or []) for p in plan_list)
            return {
                "count": len(plan_list),
                "avg_completion_score": round(avg_score, 3),
                "total_items": total_items,
            }

        a_stats = _stats(a_plans)
        b_stats = _stats(b_plans)

        # Determine winner based on avg completion score
        a_score = a_stats["avg_completion_score"]
        b_score = b_stats["avg_completion_score"]
        diff_pct = abs(a_score - b_score) / max(a_score, b_score, 0.001)

        if diff_pct < 0.05:
            winner = "tie"
        elif a_score > b_score:
            winner = "a"
        elif b_score > a_score:
            winner = "b"
        else:
            winner = "inconclusive"

        results = {
            "variant_a": a_stats,
            "variant_b": b_stats,
            "computed_at": datetime.now(UTC).isoformat(),
        }
        return results, winner

    async def get_results(
        self, db: AsyncSession, experiment_id: str, space_id: str
    ) -> ExperimentResultsResponse:
        exp = await self.get(db, experiment_id)
        if exp is None or exp.space_id != space_id:
            raise NotFoundError("Experiment not found", code="dailyos.experiment_not_found")

        results = exp.results or {}
        return ExperimentResultsResponse(
            experiment_id=exp.id,
            name=exp.name,
            status=exp.status,
            winner=exp.winner,
            variant_a_stats=results.get("variant_a", {}),
            variant_b_stats=results.get("variant_b", {}),
            analysis=self._describe_winner(exp.winner, results),
            started_at=exp.started_at,
            ended_at=exp.ended_at,
        )

    def _describe_winner(self, winner: str | None, results: dict) -> str:
        if winner == "a":
            return "Variant A outperformed Variant B based on average completion score."
        if winner == "b":
            return "Variant B outperformed Variant A based on average completion score."
        if winner == "tie":
            return "Both variants performed similarly (within 5% difference)."
        return "Results are inconclusive — insufficient data to determine a winner."


# ======================== Singletons ========================

eisenhower_service = EisenhowerService()
wizard_service = ProcrastinationWizardService()
template_service = TemplateService()
gamification_service = GamificationService()
onboarding_service = OnboardingService()
experiment_service = ExperimentService()

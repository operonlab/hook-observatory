"""Daily OS ORM models — methods, method configs, and daily plans.

All tables live in the `dailyos` PostgreSQL schema.
IDs: String(32) + uuid7().hex.

Tables (17 total):
  Existing (6): methods, method_selections, daily_plans,
    task_groups, recurring_items, activity_spans
  P1 (3): user_toggles, backlog_items, capacity_history
  P2 (4): workflows, snippets, smart_lists, pilot_state
  P3 (3): plan_templates, gamification_state, point_history
  P4 (1): experiments
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.models import SpaceScopedModel

SCHEMA = "dailyos"


class Method(SpaceScopedModel):
    """A planning method template — system preset or user-created custom."""

    __tablename__ = "methods"
    __table_args__ = (
        Index("idx_method_space", "space_id"),
        Index(
            "idx_method_unique_slug",
            "space_id",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_preset: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    cloned_from_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.methods.id", ondelete="SET NULL"), nullable=True
    )

    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))

    layout_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'list'"))

    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)


class MethodSelection(SpaceScopedModel):
    """Per-space active method selection, with optional context scoping."""

    __tablename__ = "method_selections"
    __table_args__ = (
        Index(
            "idx_ms_unique_active_method",
            "space_id",
            "context",
            "method_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND is_active = true"),
        ),
        {"schema": SCHEMA},
    )

    method_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.methods.id", ondelete="CASCADE"), nullable=False
    )

    context: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'default'"))

    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    method: Mapped["Method"] = relationship(lazy="selectin")


class DailyPlan(SpaceScopedModel):
    """A single day's plan — created using the active method strategy."""

    __tablename__ = "daily_plans"
    __table_args__ = (
        Index(
            "idx_dp_unique_date",
            "space_id",
            "plan_date",
            "context",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    context: Mapped[str] = mapped_column(Text, server_default=text("'default'"))
    method_selection_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.method_selections.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(Text, server_default=text("'planning'"))

    items: Mapped[list[dict]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))

    method_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    reflection: Mapped[str | None] = mapped_column(Text, nullable=True)
    completion_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    method_selection: Mapped["MethodSelection | None"] = relationship(lazy="selectin")


class TaskGroup(SpaceScopedModel):
    """User-defined task group for categorizing items across views."""

    __tablename__ = "task_groups"
    __table_args__ = (
        Index("idx_tg_space", "space_id"),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(Text, server_default=text("'#cba6f7'"))
    icon: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class RecurringItem(SpaceScopedModel):
    """A recurring plan item — fixed schedule events like daily sleep, weekly church, etc."""

    __tablename__ = "recurring_items"
    __table_args__ = (
        Index("idx_ri_space", "space_id"),
        Index("idx_ri_active", "space_id", "is_active"),
        {"schema": SCHEMA},
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    recurrence_type: Mapped[str] = mapped_column(Text, nullable=False)  # daily, weekly, monthly
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0=Mon..6=Sun
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-31
    start_time: Mapped[str | None] = mapped_column(Text, nullable=True)  # HH:MM
    end_time: Mapped[str | None] = mapped_column(Text, nullable=True)  # HH:MM
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.task_groups.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class ActivitySpan(SpaceScopedModel):
    """A multi-day activity span — one-time events like trips, conferences, vacations."""

    __tablename__ = "activity_spans"
    __table_args__ = (
        Index("idx_as_space", "space_id"),
        Index("idx_as_date_range", "space_id", "start_date", "end_date"),
        {"schema": SCHEMA},
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)  # inclusive
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(Text, server_default=text("'#89b4fa'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


# ======================== P1a: Micro-Strategy Toggles ========================


class UserToggle(SpaceScopedModel):
    """Per-user feature toggle — 94+ independent on/off switches."""

    __tablename__ = "user_toggles"
    __table_args__ = (
        Index("idx_ut_space", "space_id"),
        Index(
            "idx_ut_unique_key",
            "space_id",
            "toggle_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    toggle_key: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(
        Text, server_default=text("'manual'")
    )  # manual, workflow, snippet, quiz


# ======================== P1b: Task Funnel (Backlog) ========================


class BacklogItem(SpaceScopedModel):
    """Funnel upstream item — lives in backburner/master/ready before entering daily plan."""

    __tablename__ = "backlog_items"
    __table_args__ = (
        Index("idx_bi_space_layer", "space_id", "funnel_layer"),
        Index("idx_bi_space_due", "space_id", "due_date"),
        {"schema": SCHEMA},
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    funnel_layer: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'master'")
    )  # backburner, master, ready, scheduled
    priority: Mapped[str] = mapped_column(Text, server_default=text("'medium'"))
    labels: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    energy_level: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cognitive_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    do_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    parent_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.backlog_items.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_module: Mapped[str | None] = mapped_column(Text, nullable=True)  # taskflow, capture
    source_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reward_points: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    is_frog: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    defer_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # C1: low-freq fields


# ======================== P1c: Capacity History ========================


class CapacityHistory(SpaceScopedModel):
    """Daily capacity log — time + cognitive fuel actuals for auto-learning."""

    __tablename__ = "capacity_history"
    __table_args__ = (
        Index(
            "idx_ch_unique_date",
            "space_id",
            "log_date",
            "budget_type",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    budget_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'time'")
    )  # time, cognitive (C3: dual-track)
    planned_value: Mapped[float] = mapped_column(Float, server_default=text("0"))
    actual_value: Mapped[float] = mapped_column(Float, server_default=text("0"))
    unit: Mapped[str] = mapped_column(Text, server_default=text("'minutes'"))  # minutes, points
    energy_start: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    energy_end: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    mood: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ======================== P2a: Workflows ========================


class Workflow(SpaceScopedModel):
    """Strategy bundle — a coherent set of method + toggle + snippet configurations."""

    __tablename__ = "workflows"
    __table_args__ = (
        Index("idx_wf_space", "space_id"),
        Index(
            "idx_wf_unique_slug",
            "space_id",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_preset: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    category: Mapped[str] = mapped_column(
        Text, server_default=text("'methodology'")
    )  # apps, methodology, original
    method_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    toggle_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    snippet_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)  # user rating 1-5


# ======================== P2c: Snippets ========================


class Snippet(SpaceScopedModel):
    """Additive feature fragment — stackable on top of any workflow."""

    __tablename__ = "snippets"
    __table_args__ = (
        Index("idx_sn_space", "space_id"),
        Index(
            "idx_sn_unique_slug",
            "space_id",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_preset: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    toggle_keys: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    config_patch: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


# ======================== P2d: Smart Lists ========================


class SmartList(SpaceScopedModel):
    """Dynamic RPN filter — saved filter presets for cross-module querying."""

    __tablename__ = "smart_lists"
    __table_args__ = (
        Index("idx_sl_space", "space_id"),
        Index(
            "idx_sl_unique_slug",
            "space_id",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    icon: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    filter_expr: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )  # RPN token list
    sort_by: Mapped[str] = mapped_column(Text, server_default=text("'priority'"))
    group_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_preset: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    source_modules: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )  # dailyos, taskflow, finance
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)


# ======================== P2b: Pilot State ========================


class PilotState(SpaceScopedModel):
    """Pilot Method dual-track state — cognitive fuel + flight mode per day."""

    __tablename__ = "pilot_state"
    __table_args__ = (
        Index(
            "idx_ps_unique_date",
            "space_id",
            "state_date",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    state_date: Mapped[date] = mapped_column(Date, nullable=False)
    flight_mode: Mapped[str] = mapped_column(
        Text, server_default=text("'cruise'")
    )  # sprint, cruise, glide, emergency
    cognitive_fuel_budget: Mapped[float] = mapped_column(Float, server_default=text("100"))
    cognitive_fuel_spent: Mapped[float] = mapped_column(Float, server_default=text("0"))
    time_budget_min: Mapped[int] = mapped_column(Integer, server_default=text("480"))
    time_spent_min: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    verify_level: Mapped[str] = mapped_column(
        Text, server_default=text("'normal'")
    )  # skip, light, normal, thorough (validation ratchet)
    ratchet_history: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    black_box: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    decision_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    decision_fatigue_score: Mapped[float | None] = mapped_column(Float, nullable=True)


# ======================== P3c: Plan Templates ========================


class PlanTemplate(SpaceScopedModel):
    """Reusable daily plan template — save + apply common day structures."""

    __tablename__ = "plan_templates"
    __table_args__ = (
        Index("idx_pt_space", "space_id"),
        Index(
            "idx_pt_unique_slug",
            "space_id",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    items: Mapped[list[dict]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    method_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    toggle_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ======================== P3d: Gamification ========================


class GamificationState(SpaceScopedModel):
    """Per-user gamification state — points, streaks, achievements."""

    __tablename__ = "gamification_state"
    __table_args__ = (
        Index(
            "idx_gs_unique_space",
            "space_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    total_points: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    current_streak: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    longest_streak: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_streak_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    level: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    achievements: Mapped[list[dict]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )  # [{id, name, earned_at}]
    reward_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class PointHistory(SpaceScopedModel):
    """Individual point transaction — tracks every point earn/spend."""

    __tablename__ = "point_history"
    __table_args__ = (
        Index("idx_ph_space_date", "space_id", "earned_at"),
        {"schema": SCHEMA},
    )

    points: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)  # task, frog, streak, bonus
    source_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    multiplier: Mapped[float] = mapped_column(Float, server_default=text("1.0"))
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ======================== P4: Experiments ========================


class Experiment(SpaceScopedModel):
    """A/B workflow experiment — test different configurations and measure results."""

    __tablename__ = "experiments"
    __table_args__ = (
        Index("idx_ex_space", "space_id"),
        Index("idx_ex_status", "space_id", "status"),
        {"schema": SCHEMA},
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    name_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, server_default=text("'draft'")
    )  # draft, running, completed, archived
    variant_a: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )  # {workflow_id, method_ids, toggle_overrides}
    variant_b: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    duration_days: Mapped[int] = mapped_column(Integer, server_default=text("7"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    winner: Mapped[str | None] = mapped_column(Text, nullable=True)  # a, b, tie, inconclusive

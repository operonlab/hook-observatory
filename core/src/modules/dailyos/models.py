"""Daily OS ORM models — methods, method configs, and daily plans.

All tables live in the `dailyos` PostgreSQL schema.
IDs: String(32) + uuid7().hex.
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

"""Taskflow ORM models — tasks and task updates.

All tables live in the `taskflow` PostgreSQL schema.
IDs: String(32) + uuid7().hex.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.models import Base, SpaceScopedModel, TimestampMixin

SCHEMA = "taskflow"


class Task(SpaceScopedModel):
    """A task with FSM status, scheduling, priority, and subtask support."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("idx_task_space", "space_id"),
        Index("idx_task_space_status", "space_id", "status"),
        Index("idx_task_parent", "parent_id"),
        Index(
            "idx_task_due_date",
            "space_id",
            "due_date",
            postgresql_where=text("due_date IS NOT NULL AND status NOT IN ('done', 'cancelled')"),
        ),
        {"schema": SCHEMA},
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source & classification
    source: Mapped[str] = mapped_column(Text, nullable=False)  # personal / family / company
    project: Mapped[str | None] = mapped_column(Text, nullable=True)

    # FSM status
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'todo'")
    )  # todo / in_progress / review / done / blocked / cancelled

    # Scheduling
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Priority & effort
    priority: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'medium'")
    )  # urgent / high / medium / low
    estimated_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_hours: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Recurrence
    recurrence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Meta
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    # Subtask self-reference
    parent_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.tasks.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    children: Mapped[list["Task"]] = relationship(
        "Task",
        back_populates="parent",
        lazy="selectin",
    )
    parent: Mapped["Task | None"] = relationship(
        "Task",
        back_populates="children",
        remote_side="Task.id",
        lazy="selectin",
    )
    updates: Mapped[list["TaskUpdate"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", lazy="selectin"
    )


class TaskUpdate(TimestampMixin, Base):
    """Progress report / status change log for a task."""

    __tablename__ = "task_updates"
    __table_args__ = (
        Index("idx_task_update_task", "task_id"),
        {"schema": SCHEMA},
    )

    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.tasks.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # progress / blocker / note / status_change
    content: Mapped[str] = mapped_column(Text, nullable=False)
    old_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    hours_spent: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Relationships
    task: Mapped["Task"] = relationship(back_populates="updates")

"""Taskflow services — CRUD + FSM status transitions + progress tracking.

This is the PUBLIC API of the taskflow module.
Other modules import from here, never from models.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.events.types import TaskflowEvents
from src.shared.errors import BadRequestError, NotFoundError
from src.shared.fsm import emit_state_changed, validate_transition
from src.shared.models import _uuid7_hex
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService

from .lifecycle import TaskLifecycle
from .models import Task
from .models import TaskUpdate as TaskUpdateModel
from .schemas import (
    TaskCreate,
    TaskProgressStats,
    TaskResponse,
    TaskUpdate,
    TaskUpdateCreate,
    TaskUpdateResponse,
)

VALID_SOURCES = {"personal", "family", "company"}
VALID_PRIORITIES = {"urgent", "high", "medium", "low"}
VALID_STATUSES = {"todo", "in_progress", "review", "done", "blocked", "cancelled"}
VALID_UPDATE_TYPES = {"progress", "blocker", "note", "status_change"}


class TaskService(BaseCRUDService[Task, TaskCreate, TaskUpdate, TaskResponse]):
    model = Task
    audit_module = "taskflow"

    def before_create(self, data: TaskCreate, **kwargs: Any) -> dict:
        d = data.model_dump()
        if d["source"] not in VALID_SOURCES:
            raise BadRequestError(
                f"Invalid source: {d['source']}",
                code="taskflow.invalid_source",
            )
        if d.get("priority", "medium") not in VALID_PRIORITIES:
            raise BadRequestError(
                f"Invalid priority: {d['priority']}",
                code="taskflow.invalid_priority",
            )
        if d.get("status", "todo") not in VALID_STATUSES:
            raise BadRequestError(
                f"Invalid status: {d['status']}",
                code="taskflow.invalid_status",
            )
        return d

    def after_create(self, instance: Task) -> None:
        event_bus.publish_fire_and_forget(
            Event(
                type=TaskflowEvents.TASK_CREATED,
                data={
                    "task_id": instance.id,
                    "id": instance.id,
                    "space_id": instance.space_id,
                    "title": instance.title,
                    "description": instance.description,
                    "status": instance.status,
                    "priority": instance.priority,
                    "project": instance.project,
                    "tags": instance.tags or [],
                    "created_at": instance.created_at.isoformat() if instance.created_at else None,
                    "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
                },
                source="taskflow",
                user_id=instance.created_by,
            )
        )

    def after_update(self, instance: Task, changes: dict) -> None:
        event_bus.publish_fire_and_forget(
            Event(
                type=TaskflowEvents.TASK_UPDATED,
                data={
                    "task_id": instance.id,
                    "id": instance.id,
                    "space_id": instance.space_id,
                    "title": instance.title,
                    "description": instance.description,
                    "status": instance.status,
                    "priority": instance.priority,
                    "project": instance.project,
                    "tags": instance.tags or [],
                    "created_at": instance.created_at.isoformat() if instance.created_at else None,
                    "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
                },
                source="taskflow",
                user_id=instance.created_by,
            )
        )

    def after_delete(self, instance: Task) -> None:
        event_bus.publish_fire_and_forget(
            Event(
                type=TaskflowEvents.TASK_DELETED,
                data={
                    "task_id": instance.id,
                    "id": instance.id,
                    "space_id": instance.space_id,
                },
                source="taskflow",
                user_id=instance.created_by,
            )
        )

    def to_response(self, instance: Task) -> TaskResponse:
        return TaskResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            title=instance.title,
            description=instance.description,
            source=instance.source,
            project=instance.project,
            status=instance.status,
            due_date=instance.due_date,
            start_date=instance.start_date,
            completed_at=instance.completed_at,
            priority=instance.priority,
            estimated_hours=instance.estimated_hours,
            actual_hours=instance.actual_hours,
            recurrence=instance.recurrence,
            tags=instance.tags,
            parent_id=instance.parent_id,
            deleted_at=instance.deleted_at,
            subtask_count=len(instance.children) if instance.children else 0,
            update_count=len(instance.updates) if instance.updates else 0,
        )

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
        *,
        user_id: str | None = None,
        status: str | None = None,
        source: str | None = None,
        project: str | None = None,
        priority: str | None = None,
        tag: str | None = None,
        search: str | None = None,
        parent_id: str | None = "__unset__",
    ) -> PaginatedResponse[TaskResponse]:
        p = pagination or PaginationParams()
        filters = [Task.space_id == space_id, Task.deleted_at == None]  # noqa: E711

        if status:
            filters.append(Task.status == status)
        if source:
            filters.append(Task.source == source)
        if project:
            filters.append(Task.project == project)
        if priority:
            filters.append(Task.priority == priority)
        if tag:
            filters.append(Task.tags.any(tag))
        if search:
            like = f"%{search}%"
            filters.append(or_(Task.title.ilike(like), Task.description.ilike(like)))
        if parent_id == "__unset__":
            pass  # no filter on parent
        elif parent_id is None:
            filters.append(Task.parent_id == None)  # noqa: E711
        else:
            filters.append(Task.parent_id == parent_id)

        count_q = select(func.count()).select_from(Task).where(*filters)
        total = (await db.execute(count_q)).scalar_one()

        q = (
            select(Task)
            .where(*filters)
            .order_by(Task.created_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows: Sequence[Task] = (await db.execute(q)).scalars().unique().all()
        return PaginatedResponse[TaskResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def transition_status(
        self,
        db: AsyncSession,
        task_id: str,
        new_status: str,
        user_id: str | None = None,
        comment: str | None = None,
    ) -> Task:
        task = await self.get(db, task_id)
        if not task:
            raise NotFoundError("Task not found", code="taskflow.task_not_found")

        old_status = task.status
        validate_transition(TaskLifecycle, old_status, new_status, "task")

        task.status = new_status

        if new_status == "done" and not task.completed_at:
            task.completed_at = datetime.now(UTC)
        elif new_status != "done":
            task.completed_at = None

        await db.flush()
        await db.refresh(task)

        # Record status change as a TaskUpdate
        update = TaskUpdateModel(
            id=_uuid7_hex(),
            task_id=task_id,
            type="status_change",
            content=comment or f"Status changed: {old_status} -> {new_status}",
            old_status=old_status,
            new_status=new_status,
            created_by=user_id,
        )
        db.add(update)
        await db.flush()

        # Emit events
        await emit_state_changed(
            "taskflow", "task", task_id, old_status, new_status, user_id=user_id
        )

        if new_status == "done":
            await event_bus.publish(
                Event(
                    type=TaskflowEvents.TASK_COMPLETED,
                    data={"task_id": task_id, "title": task.title},
                    source="taskflow",
                    user_id=user_id,
                )
            )

        return task

    async def add_update(
        self,
        db: AsyncSession,
        task_id: str,
        data: TaskUpdateCreate,
        user_id: str | None = None,
    ) -> TaskUpdateModel:
        task = await self.get(db, task_id)
        if not task:
            raise NotFoundError("Task not found", code="taskflow.task_not_found")

        if data.type not in VALID_UPDATE_TYPES:
            raise BadRequestError(
                f"Invalid update type: {data.type}",
                code="taskflow.invalid_update_type",
            )

        update = TaskUpdateModel(
            id=_uuid7_hex(),
            task_id=task_id,
            type=data.type,
            content=data.content,
            hours_spent=data.hours_spent,
            created_by=user_id,
        )
        db.add(update)

        # Accumulate hours on task
        if data.hours_spent and data.hours_spent > 0:
            task.actual_hours = (task.actual_hours or 0) + data.hours_spent

        await db.flush()
        return update

    async def list_updates(
        self,
        db: AsyncSession,
        task_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[TaskUpdateResponse]:
        p = pagination or PaginationParams()

        count_q = (
            select(func.count())
            .select_from(TaskUpdateModel)
            .where(TaskUpdateModel.task_id == task_id)
        )
        total = (await db.execute(count_q)).scalar_one()

        q = (
            select(TaskUpdateModel)
            .where(TaskUpdateModel.task_id == task_id)
            .order_by(TaskUpdateModel.created_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[TaskUpdateResponse](
            items=[self._update_to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    def _update_to_response(self, u: TaskUpdateModel) -> TaskUpdateResponse:
        return TaskUpdateResponse(
            id=u.id,
            task_id=u.task_id,
            type=u.type,
            content=u.content,
            old_status=u.old_status,
            new_status=u.new_status,
            hours_spent=u.hours_spent,
            created_by=u.created_by,
            created_at=u.created_at,
            updated_at=u.updated_at,
        )

    async def get_today_tasks(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None = None,
    ) -> list[TaskResponse]:
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        q = (
            select(Task)
            .where(
                Task.space_id == space_id,
                Task.deleted_at == None,  # noqa: E711
                Task.status.notin_(["done", "cancelled"]),
                or_(
                    Task.due_date.between(today_start, today_end),
                    Task.start_date.between(today_start, today_end),
                ),
            )
            .order_by(Task.priority.desc(), Task.due_date.asc())
        )
        rows = (await db.execute(q)).scalars().unique().all()
        return [self.to_response(r) for r in rows]

    async def get_upcoming_tasks(
        self,
        db: AsyncSession,
        space_id: str,
        days: int = 7,
        user_id: str | None = None,
    ) -> list[TaskResponse]:
        now = datetime.now(UTC)
        from datetime import timedelta

        end = now + timedelta(days=days)

        q = (
            select(Task)
            .where(
                Task.space_id == space_id,
                Task.deleted_at == None,  # noqa: E711
                Task.status.notin_(["done", "cancelled"]),
                Task.due_date != None,  # noqa: E711
                Task.due_date <= end,
            )
            .order_by(Task.due_date.asc())
        )
        rows = (await db.execute(q)).scalars().unique().all()
        return [self.to_response(r) for r in rows]

    async def get_progress_stats(
        self,
        db: AsyncSession,
        space_id: str,
        user_id: str | None = None,
    ) -> TaskProgressStats:
        now = datetime.now(UTC)
        base = [Task.space_id == space_id, Task.deleted_at == None]  # noqa: E711

        # Total
        total = (await db.execute(select(func.count()).select_from(Task).where(*base))).scalar_one()

        # By status
        status_q = select(Task.status, func.count()).where(*base).group_by(Task.status)
        by_status = dict((await db.execute(status_q)).all())

        # By source
        source_q = select(Task.source, func.count()).where(*base).group_by(Task.source)
        by_source = dict((await db.execute(source_q)).all())

        # By priority
        priority_q = select(Task.priority, func.count()).where(*base).group_by(Task.priority)
        by_priority = dict((await db.execute(priority_q)).all())

        # Overdue
        overdue_q = (
            select(func.count())
            .select_from(Task)
            .where(
                *base,
                Task.due_date < now,
                Task.status.notin_(["done", "cancelled"]),
            )
        )
        overdue = (await db.execute(overdue_q)).scalar_one()

        # Hours
        hours_q = select(
            func.coalesce(func.sum(Task.estimated_hours), 0),
            func.coalesce(func.sum(Task.actual_hours), 0),
        ).where(*base)
        est, act = (await db.execute(hours_q)).one()

        return TaskProgressStats(
            total=total,
            by_status=by_status,
            by_source=by_source,
            by_priority=by_priority,
            overdue=overdue,
            total_estimated_hours=float(est),
            total_actual_hours=float(act),
        )


task_service = TaskService()

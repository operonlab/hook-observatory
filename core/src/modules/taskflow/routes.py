"""Taskflow routes — REST API endpoints.

Prefix: /api/taskflow (mounted in main.py)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from .schemas import (
    StatusTransitionRequest,
    TaskCreate,
    TaskProgressStats,
    TaskResponse,
    TaskSearchResult,
    TaskUpdate,
    TaskUpdateCreate,
    TaskUpdateResponse,
)
from .services import task_service

router = APIRouter(tags=["taskflow"])


# ======================== Search ========================


@router.get("/search", response_model=list[TaskSearchResult])
async def search_tasks(
    q: str = Query(..., description="Search query string"),
    space_id: str = Query("default"),
    status: str | None = Query(None, description="Filter by status"),
    priority: str | None = Query(None, description="Filter by priority"),
    top_k: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.read"),
):
    """Search tasks using Qdrant hybrid search with ILIKE fallback."""
    import logging

    from sqlalchemy import and_, select

    from src.shared.fallback_search import build_ilike_conditions
    from src.shared.qdrant_search import search_with_fallback
    from src.shared.rerank_utils import rerank_generic

    from .models import Task

    logger = logging.getLogger(__name__)

    # --- Qdrant path ---
    results, _meta = await search_with_fallback(q, space_id, "taskflow", top_k=top_k)

    if results:
        entity_ids = [r.entity_id for r in results]
        score_map = {r.entity_id: r.score for r in results}

        stmt = select(Task).where(
            Task.id.in_(entity_ids),
            Task.space_id == space_id,
            Task.deleted_at.is_(None),
        )
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if priority is not None:
            stmt = stmt.where(Task.priority == priority)

        rows = (await db.execute(stmt)).scalars().all()
        id_to_task = {t.id: t for t in rows}
        output = [
            TaskSearchResult(
                task=task_service.to_response(id_to_task[eid]),
                score=score_map[eid],
            )
            for eid in entity_ids
            if eid in id_to_task
        ]

        # Cross-encoder reranking
        if len(output) > 1:
            output = await rerank_generic(
                query=q,
                results=output,
                content_fn=lambda r: r.task.title if hasattr(r, "task") else "",
                score_fn=lambda r: r.score,
                set_score_fn=lambda r, s: setattr(r, "score", s),
            )

        return output

    logger.debug(
        "Qdrant returned 0 results for taskflow space=%s query=%r — falling back to ILIKE",
        space_id,
        q,
    )

    # --- ILIKE fallback ---
    title_conditions = build_ilike_conditions(q, Task.title)
    title_filter = and_(*title_conditions) if title_conditions else Task.title.ilike(f"%{q}%")
    stmt = select(Task).where(
        Task.space_id == space_id,
        title_filter,
        Task.deleted_at.is_(None),
    )
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)

    stmt = stmt.order_by(Task.updated_at.desc()).limit(top_k)
    rows = (await db.execute(stmt)).scalars().all()
    output = [TaskSearchResult(task=task_service.to_response(t), score=1.0) for t in rows]

    # Cross-encoder reranking
    if len(output) > 1:
        output = await rerank_generic(
            query=q,
            results=output,
            content_fn=lambda r: r.task.title if hasattr(r, "task") else "",
            score_fn=lambda r: r.score,
            set_score_fn=lambda r, s: setattr(r, "score", s),
        )

    return output


# ======================== Tasks CRUD ========================


@router.get("/tasks", response_model=PaginatedResponse[TaskResponse])
async def list_tasks(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, description="todo/in_progress/review/done/blocked/cancelled"),
    source: str | None = Query(None, description="personal/family/company"),
    project: str | None = Query(None),
    priority: str | None = Query(None, description="urgent/high/medium/low"),
    tag: str | None = Query(None),
    search: str | None = Query(None, description="Search title/description"),
    top_level: bool = Query(False, description="Only top-level tasks (no parent)"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.read"),
):
    parent_filter = None if top_level else "__unset__"
    return await task_service.list(
        db,
        space_id,
        PaginationParams(page=page, page_size=page_size),
        user_id=user.get("id"),
        status=status,
        source=source,
        project=project,
        priority=priority,
        tag=tag,
        search=search,
        parent_id=parent_filter,
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.read"),
):
    instance = await task_service.get_in_space(db, task_id, space_id)
    if not instance:
        raise NotFoundError("Task not found", code="taskflow.task_not_found")
    return task_service.to_response(instance)


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    data: TaskCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.write"),
):
    instance = await task_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return task_service.to_response(instance)


@router.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    data: TaskUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.write"),
):
    instance = await task_service.update(
        db, task_id, data, user_id=user.get("id"), space_id=space_id
    )
    if not instance:
        raise NotFoundError("Task not found", code="taskflow.task_not_found")
    await db.commit()
    return task_service.to_response(instance)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.write"),
):
    if not await task_service.delete(db, task_id, user_id=user.get("id"), space_id=space_id):
        raise NotFoundError("Task not found", code="taskflow.task_not_found")
    await db.commit()


# ======================== Subtasks ========================


@router.get("/tasks/{task_id}/subtasks", response_model=PaginatedResponse[TaskResponse])
async def list_subtasks(
    task_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.read"),
):
    parent = await task_service.get(db, task_id)
    if not parent:
        raise NotFoundError("Task not found", code="taskflow.task_not_found")
    return await task_service.list(
        db,
        parent.space_id,
        PaginationParams(page=page, page_size=page_size),
        parent_id=task_id,
    )


# ======================== Status Transitions ========================


@router.post("/tasks/{task_id}/transition", response_model=TaskResponse)
async def transition_task_status(
    task_id: str,
    data: StatusTransitionRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.write"),
):
    task = await task_service.transition_status(
        db, task_id, data.status, user_id=user.get("id"), comment=data.comment
    )
    await db.commit()
    return task_service.to_response(task)


# ======================== Task Updates (Progress) ========================


@router.get("/tasks/{task_id}/updates", response_model=PaginatedResponse[TaskUpdateResponse])
async def list_task_updates(
    task_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.read"),
):
    params = PaginationParams(page=page, page_size=page_size)
    return await task_service.list_updates(db, task_id, params)


@router.post("/tasks/{task_id}/updates", response_model=TaskUpdateResponse, status_code=201)
async def add_task_update(
    task_id: str,
    data: TaskUpdateCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.write"),
):
    update = await task_service.add_update(db, task_id, data, user_id=user.get("id"))
    await db.commit()
    return task_service._update_to_response(update)


# ======================== Views ========================


@router.get("/today", response_model=list[TaskResponse])
async def today_tasks(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.read"),
):
    return await task_service.get_today_tasks(db, space_id, user_id=user.get("id"))


@router.get("/upcoming", response_model=list[TaskResponse])
async def upcoming_tasks(
    space_id: str = Query("default"),
    days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.read"),
):
    return await task_service.get_upcoming_tasks(db, space_id, days=days, user_id=user.get("id"))


@router.get("/progress", response_model=TaskProgressStats)
async def task_progress(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.read"),
):
    return await task_service.get_progress_stats(db, space_id, user_id=user.get("id"))


# ======================== Trash (Soft Delete) ========================


@router.get("/trash", response_model=PaginatedResponse[TaskResponse])
async def list_trash(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.read"),
):
    params = PaginationParams(page=page, page_size=page_size)
    return await task_service.list_deleted(db, space_id, params)


@router.post("/trash/{task_id}/restore", response_model=TaskResponse)
async def restore_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("taskflow.write"),
):
    instance = await task_service.restore(db, task_id, user_id=user.get("id"))
    if not instance:
        raise NotFoundError("Task not found in trash", code="taskflow.not_in_trash")
    await db.commit()
    return task_service.to_response(instance)

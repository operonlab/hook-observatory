"""Team-task project management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent_metrics.db import get_pool
from agent_metrics.engines import task_manager as tm
from agent_metrics.models import (
    DebaterAdd,
    ProjectCreate,
    RoundAction,
    TaskAdd,
    TaskResult,
    TaskUpdate,
)

router = APIRouter()


@router.get("/")
async def list_projects() -> list[dict]:
    pool = await get_pool()
    return await tm.list_projects(pool)


@router.post("/")
async def create_project(body: ProjectCreate) -> dict:
    pool = await get_pool()
    try:
        proj = await tm.init_project(
            pool,
            body.name,
            body.mode.value,
            goal=body.goal,
            pipeline=body.pipeline,
            workspace=body.workspace,
        )
        return {"status": "created", "project": proj}
    except FileExistsError as e:
        raise HTTPException(400, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/{name}")
async def get_project(name: str) -> dict:
    pool = await get_pool()
    try:
        return await tm.get_status(pool, name)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None


@router.post("/{name}/tasks")
async def add_task(name: str, body: TaskAdd) -> dict:
    pool = await get_pool()
    try:
        task = await tm.add_task(
            pool,
            name,
            body.task_id,
            agent=body.agent,
            desc=body.description,
            deps=body.deps,
        )
        return {"status": "added", "task": task}
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e)) from None


@router.get("/{name}/ready")
async def ready_tasks(name: str) -> list[dict]:
    pool = await get_pool()
    try:
        return await tm.get_ready_tasks(pool, name)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e)) from None


@router.get("/{name}/next")
async def next_stage(name: str) -> dict:
    pool = await get_pool()
    try:
        stage = await tm.get_next_stage(pool, name)
        if stage is None:
            return {"status": "all_complete"}
        return stage
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e)) from None


@router.patch("/{name}/tasks/{task_id}")
async def update_task(name: str, task_id: str, body: TaskUpdate) -> dict:
    pool = await get_pool()
    try:
        return await tm.update_task_status(pool, name, task_id, body.status.value)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e)) from None


@router.post("/{name}/tasks/{task_id}/result")
async def record_result(name: str, task_id: str, body: TaskResult) -> dict:
    pool = await get_pool()
    try:
        await tm.record_result(pool, name, task_id, body.text)
        return {"status": "recorded"}
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e)) from None


@router.post("/{name}/debaters")
async def add_debater(name: str, body: DebaterAdd) -> dict:
    pool = await get_pool()
    try:
        debater = await tm.add_debater(
            pool,
            name,
            body.debater_id,
            agent=body.agent,
            perspective=body.perspective,
        )
        return {"status": "added", "debater": debater}
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e)) from None


@router.post("/{name}/rounds")
async def manage_round(name: str, body: RoundAction) -> dict:
    pool = await get_pool()
    try:
        return await tm.manage_round(
            pool,
            name,
            body.action,
            debater_id=body.debater_id,
            text=body.text,
        )
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e)) from None


@router.post("/{name}/reset")
async def reset_project(name: str) -> dict:
    pool = await get_pool()
    try:
        await tm.reset_project(pool, name)
        return {"status": "reset"}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from None

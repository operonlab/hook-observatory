"""Taskflow capture adapter — task."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.taskflow.schemas import TaskCreate

from .adapters import BaseCaptureAdapter


class TaskCaptureAdapter(BaseCaptureAdapter):
    module = "taskflow"
    entity_type = "task"
    default_ttl_days = 30
    enrichment_adapter_type = "taskflow"

    field_weights = {
        "title": 30,
        "source": 20,
        "priority": 15,
        "due_date": 15,
        "description": 10,
        "project": 10,
    }

    default_values = {
        "source": "personal",
        "priority": "medium",
        "status": "todo",
    }

    def smart_defaults(self, payload: dict[str, Any], user_prefs: dict[str, Any]) -> dict[str, Any]:
        result = {**self.default_values, **payload}

        if result.get("source") is None:
            result["source"] = "personal"

        if result.get("priority") is None:
            result["priority"] = "medium"

        if result.get("status") is None:
            result["status"] = "todo"

        return result

    async def promote(
        self,
        payload: dict[str, Any],
        db: AsyncSession,
        space_id: str,
        created_by: str | None,
    ) -> str:
        from src.modules.taskflow.services import task_service

        tags = payload.pop("tags", None)
        data = TaskCreate(**payload, tags=tags)
        instance = await task_service.create(db, space_id, data, created_by)
        return instance.id


ADAPTERS: list[BaseCaptureAdapter] = [TaskCaptureAdapter()]

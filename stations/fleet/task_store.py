"""In-memory task state machine with optional Redis persistence."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from uuid_utils import uuid7


class TaskStatus(str, Enum):
    PENDING = "pending"
    PREPARING = "preparing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: str
    command: str
    mode: str  # "code" or "gpu"
    node: str
    status: TaskStatus = TaskStatus.PENDING
    tmux_session: str | None = None
    branch: str | None = None
    timeout: int = 600
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    output: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "command": self.command,
            "mode": self.mode,
            "node": self.node,
            "status": self.status.value,
            "tmux_session": self.tmux_session,
            "branch": self.branch,
            "timeout": self.timeout,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


class TaskStore:
    """In-memory task storage."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}

    def create(self, command: str, mode: str, node: str, timeout: int = 600) -> Task:
        task_id = uuid7().hex
        task = Task(
            id=task_id,
            command=command,
            mode=mode,
            node=node,
            timeout=timeout,
        )
        self._tasks[task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def update_status(self, task_id: str, status: TaskStatus, **kwargs) -> Task | None:
        task = self._tasks.get(task_id)
        if not task:
            return None
        task.status = status
        for k, v in kwargs.items():
            if hasattr(task, k):
                setattr(task, k, v)
        return task

    def list_tasks(
        self,
        *,
        status: str | None = None,
        node: str | None = None,
        limit: int = 50,
    ) -> list[Task]:
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status.value == status]
        if node:
            tasks = [t for t in tasks if t.node == node]
        # Sort by created_at descending
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

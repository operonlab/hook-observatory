"""Taskflow API client — Core module at /api/taskflow.

Wraps tasks, subtasks, status transitions, progress updates, and view endpoints.

Usage:
    from workshop.clients.taskflow import TaskflowClient

    client = TaskflowClient()
    tasks = client.list_tasks(status="in_progress")
    today = client.get_today()
"""

from typing import Any

from ._base import BaseClient


class TaskflowError(Exception):
    """Raised on Taskflow API errors."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Taskflow error {status_code}: {detail}")


class TaskflowClient(BaseClient):
    """HTTP client for the Taskflow Core API module.

    Args:
        base_url: Core API URL. Defaults to CORE_API_URL env or localhost:8801.
        space_id: Space ID. Defaults to WORKSHOP_SPACE_ID env or "default".
        timeout: Default request timeout in seconds.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(module="taskflow", **kwargs)

    # ======================== Tasks ========================

    def list_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        source: str | None = None,
        project: str | None = None,
        priority: str | None = None,
        tag: str | None = None,
        search: str | None = None,
        top_level: bool | None = None,
    ) -> dict:
        """List tasks with optional filters. GET /tasks"""
        return self._get(
            "/tasks",
            {
                "page": page,
                "page_size": page_size,
                "status": status,
                "source": source,
                "project": project,
                "priority": priority,
                "tag": tag,
                "search": search,
                "top_level": top_level,
            },
        )

    def get_task(self, task_id: str) -> dict:
        """Get a single task by ID. GET /tasks/{task_id}"""
        return self._get(f"/tasks/{task_id}")

    def create_task(self, data: dict) -> dict:
        """Create a new task. POST /tasks

        data keys:
            title (str): Task title.
            description (str, optional): Task description.
            source (str): Task source (e.g. "manual", "claude").
            project (str, optional): Project name or ID.
            status (str): Initial status, default "todo".
            due_date (str, optional): ISO-8601 due datetime.
            start_date (str, optional): ISO-8601 start datetime.
            priority (str): Priority level, default "medium".
            estimated_hours (float, optional): Estimated effort in hours.
            recurrence (dict, optional): Recurrence rule.
            tags (list[str], optional): List of tag strings.
            parent_id (str, optional): Parent task UUID for subtasks.
        """
        return self._post("/tasks", data)

    def update_task(self, task_id: str, data: dict) -> dict:
        """Update an existing task. PUT /tasks/{task_id}

        data keys (all optional):
            title, description, source, project, due_date, start_date,
            priority, estimated_hours, actual_hours, recurrence, tags, parent_id.
        """
        return self._put(f"/tasks/{task_id}", data)

    def delete_task(self, task_id: str) -> None:
        """Soft-delete a task. DELETE /tasks/{task_id}"""
        self._delete(f"/tasks/{task_id}")

    # ======================== Subtasks ========================

    def list_subtasks(self, task_id: str, page: int = 1, page_size: int = 20) -> dict:
        """List subtasks of a task. GET /tasks/{task_id}/subtasks"""
        return self._get(
            f"/tasks/{task_id}/subtasks",
            {"page": page, "page_size": page_size},
        )

    # ======================== Status Transitions ========================

    def transition_status(self, task_id: str, status: str, comment: str | None = None) -> dict:
        """Transition a task to a new status. POST /tasks/{task_id}/transition

        Args:
            task_id: Task UUID.
            status: Target status (e.g. "in_progress", "done", "blocked").
            comment: Optional comment for the transition.
        """
        return self._post(
            f"/tasks/{task_id}/transition",
            {"status": status, "comment": comment},
        )

    # ======================== Task Updates (Progress) ========================

    def list_updates(self, task_id: str, page: int = 1, page_size: int = 20) -> dict:
        """List progress updates for a task. GET /tasks/{task_id}/updates"""
        return self._get(
            f"/tasks/{task_id}/updates",
            {"page": page, "page_size": page_size},
        )

    def add_update(self, task_id: str, data: dict) -> dict:
        """Add a progress update to a task. POST /tasks/{task_id}/updates

        data keys:
            type (str): Update type — progress | blocker | note | status_change.
            content (str): Update content/message.
            hours_spent (float, optional): Hours spent on this update.
        """
        return self._post(f"/tasks/{task_id}/updates", data)

    # ======================== Views ========================

    def get_today(self) -> dict:
        """Get today's tasks. GET /today"""
        return self._get("/today")

    def get_upcoming(self, days: int = 7) -> dict:
        """Get upcoming tasks. GET /upcoming

        Args:
            days: Number of days to look ahead, default 7.
        """
        return self._get("/upcoming", {"days": days})

    def get_progress(self) -> dict:
        """Get progress statistics. GET /progress"""
        return self._get("/progress")

    # ======================== Trash ========================

    def list_trash(self, page: int = 1, page_size: int = 20) -> dict:
        """List soft-deleted tasks. GET /trash"""
        return self._get("/trash", {"page": page, "page_size": page_size})

    def restore_task(self, task_id: str) -> dict:
        """Restore a task from trash. POST /trash/{task_id}/restore"""
        return self._post(f"/trash/{task_id}/restore")

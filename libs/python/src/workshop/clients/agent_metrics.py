"""Agent Metrics API client — station at port 8795.

Wraps the orchestration HTTP API (Maestro dispatch + Project management).
Unlike Core API clients (which inherit BaseClient), this wraps a station API.

Usage:
    from workshop.clients.agent_metrics import AgentMetricsClient

    client = AgentMetricsClient()

    # Maestro dispatch
    analysis = client.plan("Fix the login bug")
    result = client.run("Build user registration", budget="balanced")

    # Project management (team-tasks)
    client.create_project("my-feature", mode="dag", goal="Build auth")
    client.add_task("my-feature", "backend", agent="code-agent", deps="design")
    ready = client.ready_tasks("my-feature")
"""

import os
from typing import Any

import httpx


class AgentMetricsError(Exception):
    """Raised when the Agent Metrics API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Agent Metrics error {status_code}: {detail}")


class AgentMetricsClient:
    """HTTP client for Agent Metrics station (port 8795).

    Args:
        base_url: API URL. Defaults to AGENT_METRICS_URL env or http://localhost:8795.
        timeout: Default request timeout in seconds.
        dispatch_timeout: Timeout for long-running dispatch operations.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 15,
        dispatch_timeout: float = 600,
    ):
        self.base_url = (
            base_url or os.environ.get("AGENT_METRICS_URL", "http://localhost:8795")
        ).rstrip("/")
        self._timeout = timeout
        self._dispatch_timeout = dispatch_timeout
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def _request(
        self, method: str, path: str, timeout: float | None = None, **kwargs: Any
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            resp = self.client.request(method, url, timeout=timeout or self._timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.ConnectError:
            raise AgentMetricsError(
                0,
                f"Cannot connect to Agent Metrics at {self.base_url}. "
                "Start server: cd stations/agent-metrics && python -m agent_metrics serve",
            ) from None
        except httpx.HTTPStatusError as e:
            raise AgentMetricsError(e.response.status_code, e.response.text[:500]) from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("GET", path, params=filtered).json()

    def _post(self, path: str, body: dict | None = None, timeout: float | None = None) -> Any:
        return self._request("POST", path, json=body or {}, timeout=timeout).json()

    def _patch(self, path: str, body: dict | None = None) -> Any:
        return self._request("PATCH", path, json=body or {}).json()

    # ======================== Health ========================

    def health(self) -> dict:
        """Health check. GET /health"""
        return self._get("/health")

    def is_running(self) -> bool:
        """Check if Agent Metrics is reachable."""
        try:
            self.health()
            return True
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("health check failed: %s", e)
            return False

    # ======================== Maestro Dispatch ========================

    def plan(
        self,
        task: str,
        budget: str = "balanced",
        pattern: str | None = None,
    ) -> dict:
        """Analyze a task and return recommended orchestration pattern.

        POST /maestro/plan
        """
        body: dict[str, Any] = {"task": task, "budget": budget}
        if pattern:
            body["pattern"] = pattern
        return self._post("/maestro/plan", body)

    def run(
        self,
        task: str,
        budget: str = "balanced",
        pattern: str | None = None,
        cwd: str = "",
        timeout: int = 300,
    ) -> dict:
        """Analyze + execute a dispatch.

        POST /maestro/run
        """
        body: dict[str, Any] = {
            "task": task,
            "budget": budget,
            "cwd": cwd,
            "timeout": timeout,
        }
        if pattern:
            body["pattern"] = pattern
        return self._post("/maestro/run", body, timeout=self._dispatch_timeout)

    def list_runs(self, limit: int = 50) -> list[dict]:
        """List dispatch run history. GET /maestro/runs"""
        return self._get("/maestro/runs", {"limit": limit})

    def get_run(self, name: str) -> dict:
        """Get details of a specific dispatch run. GET /maestro/runs/{name}"""
        return self._get(f"/maestro/runs/{name}")

    def routing_table(self) -> dict:
        """Return CLI routing configuration. GET /maestro/routing-table"""
        return self._get("/maestro/routing-table")

    # ======================== Projects (Team-Tasks) ========================

    def list_projects(self) -> list[dict]:
        """List all projects. GET /projects/"""
        return self._get("/projects/")

    def create_project(
        self,
        name: str,
        mode: str = "dag",
        goal: str = "",
        pipeline: str = "",
        workspace: str = "",
    ) -> dict:
        """Create a new project. POST /projects/"""
        return self._post(
            "/projects/",
            {
                "name": name,
                "mode": mode,
                "goal": goal,
                "pipeline": pipeline,
                "workspace": workspace,
            },
        )

    def get_project(self, name: str) -> dict:
        """Get project status. GET /projects/{name}"""
        return self._get(f"/projects/{name}")

    def add_task(
        self,
        project: str,
        task_id: str,
        agent: str = "",
        description: str = "",
        deps: str = "",
    ) -> dict:
        """Add a task to a DAG project. POST /projects/{name}/tasks"""
        return self._post(
            f"/projects/{project}/tasks",
            {
                "task_id": task_id,
                "agent": agent,
                "description": description,
                "deps": deps,
            },
        )

    def ready_tasks(self, project: str) -> list[dict]:
        """Get ready-to-dispatch tasks (DAG mode). GET /projects/{name}/ready"""
        return self._get(f"/projects/{project}/ready")

    def next_stage(self, project: str) -> dict:
        """Get next stage (linear mode). GET /projects/{name}/next"""
        return self._get(f"/projects/{project}/next")

    def update_task(self, project: str, task_id: str, status: str) -> dict:
        """Update task status. PATCH /projects/{name}/tasks/{task_id}"""
        return self._patch(
            f"/projects/{project}/tasks/{task_id}",
            {"status": status},
        )

    def record_result(self, project: str, task_id: str, text: str) -> dict:
        """Record task result. POST /projects/{name}/tasks/{task_id}/result"""
        return self._post(
            f"/projects/{project}/tasks/{task_id}/result",
            {"text": text},
        )

    def add_debater(
        self,
        project: str,
        debater_id: str,
        agent: str = "",
        perspective: str = "",
    ) -> dict:
        """Add a debater (debate mode). POST /projects/{name}/debaters"""
        return self._post(
            f"/projects/{project}/debaters",
            {
                "debater_id": debater_id,
                "agent": agent,
                "perspective": perspective,
            },
        )

    def manage_round(
        self,
        project: str,
        action: str,
        debater_id: str = "",
        text: str = "",
    ) -> dict:
        """Manage debate round. POST /projects/{name}/rounds"""
        return self._post(
            f"/projects/{project}/rounds",
            {"action": action, "debater_id": debater_id, "text": text},
        )

    def reset_project(self, project: str) -> dict:
        """Reset all task states in a project. POST /projects/{name}/reset"""
        return self._post(f"/projects/{project}/reset")

    # ======================== Context Manager ========================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"AgentMetricsClient(base_url={self.base_url!r})"

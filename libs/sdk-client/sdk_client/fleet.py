"""Fleet Station SDK client — multi-machine task dispatch.

Wraps the Fleet Station HTTP API (task dispatch, node management).

Usage:
    from sdk_client.fleet import FleetClient

    client = FleetClient()

    # Dispatch a task
    task = client.dispatch("claude -p 'analyze this'", mode="code", node="win-gpu")
    print(task["id"])

    # Check status
    status = client.task_status(task["id"])
    print(status["status"])

    # Get output
    output = client.task_output(task["id"])
    print(output["output"])
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class FleetError(Exception):
    """Raised when the Fleet API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Fleet error {status_code}: {detail}")


class FleetClient:
    """HTTP client for Fleet Station API.

    Args:
        base_url: API URL. Defaults to FLEET_URL env or port_registry.
        timeout: Default request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30,
    ):
        from sdk_client import port_registry

        self.base_url = (
            base_url or os.environ.get("FLEET_URL", port_registry.get_url("fleet"))
        ).rstrip("/")
        self._timeout = timeout
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
            raise FleetError(
                0,
                f"Cannot connect to Fleet at {self.base_url}. "
                "Start server: cd stations/fleet && python -m fleet serve",
            ) from None
        except httpx.HTTPStatusError as e:
            raise FleetError(e.response.status_code, e.response.text[:500]) from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("GET", path, params=filtered).json()

    def _post(self, path: str, body: dict | None = None, timeout: float | None = None) -> Any:
        return self._request("POST", path, json=body or {}, timeout=timeout).json()

    # ======================== Health ========================

    def health(self) -> dict:
        """Health check including all node statuses. GET /health"""
        return self._get("/health")

    def is_running(self) -> bool:
        """Check if Fleet is reachable."""
        try:
            self.health()
            return True
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("fleet health check failed: %s", e)
            return False

    # ======================== Nodes ========================

    def list_nodes(self) -> list[dict]:
        """List all registered nodes with capabilities and health. GET /nodes"""
        return self._get("/nodes")

    def node_health(self, name: str) -> dict:
        """Get health status for a specific node. GET /nodes/{name}/health"""
        return self._get(f"/nodes/{name}/health")

    # ======================== Tasks ========================

    def dispatch(
        self,
        command: str,
        *,
        mode: str = "code",
        node: str | None = None,
        timeout: int = 600,
    ) -> dict:
        """Dispatch a task to a Fleet node.

        POST /tasks/dispatch

        Args:
            command: Task command or prompt string.
            mode: Execution mode — "code" (Claude Code) or "gpu" (GPU workload).
            node: Target node name. If None, Fleet auto-selects.
            timeout: Task timeout in seconds.
        """
        return self._post(
            "/tasks/dispatch",
            {"command": command, "mode": mode, "node": node, "timeout": timeout},
            timeout=float(timeout) + 30,
        )

    def task_status(self, task_id: str) -> dict:
        """Get task status and metadata. GET /tasks/{task_id}"""
        return self._get(f"/tasks/{task_id}")

    def task_output(self, task_id: str, lines: int = 200) -> dict:
        """Get task output (stdout/stderr). GET /tasks/{task_id}/output"""
        return self._get(f"/tasks/{task_id}/output", params={"lines": lines})

    def list_tasks(
        self,
        *,
        status: str | None = None,
        node: str | None = None,
    ) -> list[dict]:
        """List tasks with optional filters. GET /tasks"""
        return self._get("/tasks", params={"status": status, "node": node})

    def cancel_task(self, task_id: str) -> dict:
        """Cancel a running or pending task. POST /tasks/{task_id}/cancel"""
        return self._post(f"/tasks/{task_id}/cancel")

    # ======================== Context Manager ========================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"FleetClient(base_url={self.base_url!r})"

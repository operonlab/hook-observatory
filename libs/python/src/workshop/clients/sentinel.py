"""Sentinel API client -- health monitoring station at port 4101.

Wraps the Sentinel HTTP API (health checks, incidents, operations, uptime).
Unlike Core API clients (which inherit BaseClient), this wraps a station API.

Usage:
    from workshop.clients.sentinel import SentinelClient

    client = SentinelClient()

    # Health
    if client.is_running():
        summary = client.get_status_summary()

    # Incidents
    incidents = client.list_incidents(page=1, page_size=10)

    # Operations
    ops = client.list_operations()
"""

import os
from typing import Any

import httpx


class SentinelError(Exception):
    """Raised when the Sentinel API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Sentinel error {status_code}: {detail}")


class SentinelClient:
    """HTTP client for Sentinel station (port 4101).

    Args:
        base_url: API URL. Defaults to SENTINEL_URL env or http://localhost:4101.
        timeout: Default request timeout in seconds.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 15):
        self.base_url = (
            base_url or os.environ.get("SENTINEL_URL", "http://localhost:4101")
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
            raise SentinelError(
                0,
                f"Cannot connect to Sentinel at {self.base_url}. "
                "Start server: cd stations/sentinel && uv run python main.py",
            ) from None
        except httpx.HTTPStatusError as e:
            raise SentinelError(e.response.status_code, e.response.text[:500]) from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("GET", path, params=filtered).json()

    def _post(self, path: str, body: dict | None = None, timeout: float | None = None) -> Any:
        return self._request("POST", path, json=body or {}, timeout=timeout).json()

    # ======================== Health ========================

    def health(self) -> dict:
        """Health check. GET /api/sentinel/health"""
        return self._get("/api/sentinel/health")

    def is_running(self) -> bool:
        """Check if Sentinel is reachable."""
        try:
            self.health()
            return True
        except Exception:
            return False

    # ======================== Status (Overview) ========================

    def get_status_summary(self) -> dict:
        """Overall status with all services. GET /api/sentinel/status"""
        return self._get("/api/sentinel/status")

    def get_service_status(self, service: str) -> dict:
        """Status of a single service. GET /api/sentinel/status/{service}"""
        return self._get(f"/api/sentinel/status/{service}")

    # ======================== Incidents ========================

    def list_incidents(self, page: int = 1, page_size: int = 20) -> dict:
        """List incidents (paginated). GET /api/sentinel/incidents"""
        return self._get("/api/sentinel/incidents", {"page": page, "page_size": page_size})

    def get_incident(self, incident_id: str) -> dict:
        """Get a single incident. GET /api/sentinel/incidents/{id}"""
        return self._get(f"/api/sentinel/incidents/{incident_id}")

    # ======================== Operations ========================

    def list_operations(self) -> list[dict]:
        """List active operations. GET /api/sentinel/operations"""
        return self._get("/api/sentinel/operations")

    def notify_operation(
        self,
        service: str,
        action: str,
        agent_id: str,
        pid: int | None = None,
        estimated_duration: int = 300,
    ) -> dict:
        """Notify Sentinel of an agent operation. POST /api/sentinel/notify"""
        body: dict[str, Any] = {
            "service": service,
            "action": action,
            "agent_id": agent_id,
            "estimated_duration": estimated_duration,
        }
        if pid is not None:
            body["pid"] = pid
        return self._post("/api/sentinel/notify", body)

    def resolve_operation(self, service: str, agent_id: str, result: str = "success") -> dict:
        """Resolve an active operation. POST /api/sentinel/resolve"""
        return self._post(
            "/api/sentinel/resolve",
            {"service": service, "agent_id": agent_id, "result": result},
        )

    # ======================== Uptime ========================

    def get_uptime(self, days: int = 90) -> dict:
        """Per-service uptime data. GET /api/sentinel/uptime"""
        return self._get("/api/sentinel/uptime", {"days": days})

    # ======================== Subscriptions ========================

    def subscribe(self, url: str, events: list[str] | None = None) -> dict:
        """Subscribe to incident notifications. POST /api/sentinel/subscribe"""
        body: dict[str, Any] = {"url": url}
        if events:
            body["events"] = events
        return self._post("/api/sentinel/subscribe", body)

    # ======================== Context Manager ========================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"SentinelClient(base_url={self.base_url!r})"

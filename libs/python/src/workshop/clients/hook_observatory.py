"""Hook Observatory API client — station at port 4100.

Unlike Core API clients (which inherit BaseClient), this wraps a station API
with its own auth mechanism (X-Local-Key header).

Usage:
    from workshop.clients.hook_observatory import HookObservatoryClient

    client = HookObservatoryClient()
    stats = client.summary()
    events = client.list_events(tool_name="Bash", limit=10)
"""

import os
from typing import Any

import httpx


class HookObservatoryError(Exception):
    """Raised when the Hook Observatory API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Hook Observatory error {status_code}: {detail}")


class HookObservatoryClient:
    """HTTP client for Hook Observatory station (port 4100).

    Args:
        base_url: API URL. Defaults to HOOK_OBS_URL env or http://localhost:4100.
        secret_key: Auth key for X-Local-Key header. Defaults to HOOK_OBS_SECRET_KEY env.
        timeout: Default request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str | None = None,
        secret_key: str | None = None,
        timeout: float = 15,
    ):
        self.base_url = (
            base_url or os.environ.get("HOOK_OBS_URL", "http://localhost:4100")
        ).rstrip("/")
        self.secret_key = secret_key or os.environ.get("HOOK_OBS_SECRET_KEY", "workshop-v2-dev-key")
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

    def _headers(self) -> dict[str, str]:
        return {"x-local-key": self.secret_key}

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            resp = self.client.request(method, url, headers=self._headers(), **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.ConnectError:
            raise HookObservatoryError(
                0,
                f"Cannot connect to Hook Observatory at {self.base_url}. "
                "Start server: cd stations/hook-observatory && uv run hook-observatory",
            ) from None
        except httpx.HTTPStatusError as e:
            raise HookObservatoryError(e.response.status_code, e.response.text[:500]) from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("GET", path, params=filtered).json()

    def _post(self, path: str, body: dict | None = None) -> Any:
        return self._request("POST", path, json=body or {}).json()

    # ======================== Public (no auth) ========================

    def health(self) -> dict:
        """Health check. GET /api/health"""
        return self._get("/api/health")

    def ingest(
        self,
        event_type: str,
        data: dict | None = None,
        session_id: str | None = None,
    ) -> dict:
        """Ingest a hook event. POST /api/events"""
        body: dict = {"event_type": event_type}
        if data:
            body.update(data)
        if session_id:
            body["session_id"] = session_id
        return self._post("/api/events", body)

    # ======================== Authenticated ========================

    def summary(self) -> dict:
        """Summary stats: total, today, unique_sessions. GET /api/stats/summary"""
        return self._get("/api/stats/summary")

    def stats_by_event(self) -> list:
        """Event counts grouped by event_type. GET /api/stats/by-event"""
        return self._get("/api/stats/by-event")

    def stats_by_tool(self, limit: int = 20) -> list:
        """Tool usage ranking. GET /api/stats/by-tool"""
        return self._get("/api/stats/by-tool", {"limit": limit})

    def stats_by_session(self, limit: int = 20) -> list:
        """Recent sessions with event counts. GET /api/stats/by-session"""
        return self._get("/api/stats/by-session", {"limit": limit})

    def timeline(self, range: str = "7d", granularity: str = "hour") -> list:
        """Time-series event counts. GET /api/stats/timeline"""
        return self._get("/api/stats/timeline", {"range": range, "granularity": granularity})

    def list_events(
        self,
        event_type: str | None = None,
        session_id: str | None = None,
        tool_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Paginated event list with filters. GET /api/events"""
        return self._get(
            "/api/events",
            {
                "event_type": event_type,
                "session_id": session_id,
                "tool_name": tool_name,
                "limit": limit,
                "offset": offset,
            },
        )

    # ======================== Convenience ========================

    def is_running(self) -> bool:
        """Check if Hook Observatory is reachable."""
        try:
            self.health()
            return True
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("health check failed: %s", e)
            return False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"HookObservatoryClient(base_url={self.base_url!r})"

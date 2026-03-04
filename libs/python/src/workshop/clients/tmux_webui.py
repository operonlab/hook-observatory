"""tmux-webui SDK -- wraps the tmux-webui HTTP API (port 9527).

Provides programmatic access to tmux session/window/pane listing,
autocomplete, and relay dispatch. WebSocket endpoints are NOT wrapped.

Usage:
    from workshop.clients.tmux_webui import TmuxWebuiClient

    client = TmuxWebuiClient()

    # List sessions
    sessions = client.list_sessions()

    # Relay dispatch
    result = client.relay_dispatch("echo hello")

    # Check relay status
    status = client.relay_check("/tmp/relay-xxx.done")
"""

import os
from typing import Any

import httpx


class TmuxWebuiError(Exception):
    """Raised when the tmux-webui API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"tmux-webui error {status_code}: {detail}")


class TmuxWebuiClient:
    """HTTP client for tmux-webui station (port 9527).

    Args:
        base_url: API URL. Defaults to TMUX_WEBUI_URL env or http://localhost:9527.
        timeout: Default request timeout in seconds.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 30):
        self.base_url = (
            base_url or os.environ.get("TMUX_WEBUI_URL", "http://localhost:9527")
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
            raise TmuxWebuiError(
                0,
                f"Cannot connect to tmux-webui at {self.base_url}. "
                "Start server: uv run stations/tmux-webui/server.py",
            ) from None
        except httpx.HTTPStatusError as e:
            raise TmuxWebuiError(e.response.status_code, e.response.text[:500]) from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("GET", path, params=filtered).json()

    def _post(self, path: str, body: dict | None = None, timeout: float | None = None) -> Any:
        return self._request("POST", path, json=body or {}, timeout=timeout).json()

    # ======================== Sessions ========================

    def list_sessions(self) -> list[dict]:
        """List all tmux sessions. GET /api/sessions"""
        return self._get("/api/sessions")

    def list_windows(self, session: str) -> list[dict]:
        """List windows in a tmux session. GET /api/sessions/{session}/windows"""
        return self._get(f"/api/sessions/{session}/windows")

    def list_panes(self, session: str) -> list[dict]:
        """List panes in a tmux session. GET /api/sessions/{session}/panes"""
        return self._get(f"/api/sessions/{session}/panes")

    # ======================== Autocomplete ========================

    def autocomplete(self, query: str, type: str | None = None) -> dict:
        """Get autocomplete suggestions. GET /api/autocomplete"""
        return self._get("/api/autocomplete", {"q": query, "type": type})

    def refresh_autocomplete(self) -> dict:
        """Refresh autocomplete cache. GET /api/autocomplete/refresh"""
        return self._get("/api/autocomplete/refresh")

    # ======================== Relay ========================

    def relay_dispatch(self, command: str, timeout: int = 30) -> dict:
        """Dispatch a command to a relay pane. POST /api/relay"""
        return self._post(
            "/api/relay", {"command": command, "timeout": timeout}, timeout=timeout + 10
        )

    def relay_check(self, signal_file: str) -> dict:
        """Check if a relay command has completed. GET /api/relay/check"""
        return self._get("/api/relay/check", {"signal_file": signal_file})

    # ======================== Context Manager ========================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"TmuxWebuiClient(base_url={self.base_url!r})"

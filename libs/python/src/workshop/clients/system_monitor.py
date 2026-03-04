"""System Monitor API client -- hardware monitoring station at port 9526.

Wraps the System Monitor HTTP API (status, services, disk, alerts, reports).
Unlike Core API clients (which inherit BaseClient), this wraps a station API.

Usage:
    from workshop.clients.system_monitor import SystemMonitorClient

    client = SystemMonitorClient()

    # Health
    if client.is_running():
        status = client.get_status()

    # Services
    services = client.list_services()

    # Disk
    summary = client.disk_summary()

    # Alerts
    alerts = client.list_alerts()
"""

import os
from typing import Any

import httpx


class SystemMonitorError(Exception):
    """Raised when the System Monitor API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"SystemMonitor error {status_code}: {detail}")


class SystemMonitorClient:
    """HTTP client for System Monitor station (port 9526).

    Args:
        base_url: API URL. Defaults to SYSTEM_MONITOR_URL env or http://localhost:9526.
        timeout: Default request timeout in seconds.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 30):
        self.base_url = (
            base_url or os.environ.get("SYSTEM_MONITOR_URL", "http://localhost:9526")
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
            raise SystemMonitorError(
                0,
                f"Cannot connect to System Monitor at {self.base_url}. "
                "Start server: cd stations/system-monitor && uv run python api.py",
            ) from None
        except httpx.HTTPStatusError as e:
            raise SystemMonitorError(e.response.status_code, e.response.text[:500]) from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("GET", path, params=filtered).json()

    def _post(self, path: str, body: dict | None = None, timeout: float | None = None) -> Any:
        return self._request("POST", path, json=body or {}, timeout=timeout).json()

    # ======================== Health ========================

    def health(self) -> dict:
        """Health check. GET /health"""
        return self._get("/health")

    def is_running(self) -> bool:
        """Check if System Monitor is reachable."""
        try:
            self.health()
            return True
        except Exception:
            return False

    # ======================== Status ========================

    def get_status(self) -> dict:
        """Latest hardware metrics + pressure level. GET /status"""
        return self._get("/status")

    def get_history(self) -> dict:
        """Historical snapshots (max 30). GET /history"""
        return self._get("/history")

    # ======================== Services ========================

    def list_services(self) -> dict:
        """List all services (plist + launchd + Docker). GET /services"""
        return self._get("/services")

    def enable_service(self, label: str) -> dict:
        """Enable a launchd service. POST /services/{label}/enable"""
        return self._post(f"/services/{label}/enable")

    def disable_service(self, label: str) -> dict:
        """Disable a launchd service. POST /services/{label}/disable"""
        return self._post(f"/services/{label}/disable")

    def restart_service(self, label: str) -> dict:
        """Restart a service. POST /services/{label}/restart"""
        return self._post(f"/services/{label}/restart")

    def get_service_logs(self, label: str, lines: int = 50) -> dict:
        """Get recent log lines for a service. GET /services/{label}/logs"""
        return self._get(f"/services/{label}/logs", {"lines": lines})

    # ======================== Disk ========================

    def disk_summary(self) -> dict:
        """Lightweight disk summary via APFS query (~1s). GET /disk/summary"""
        return self._get("/disk/summary")

    def disk_scan(self) -> dict:
        """Full disk scan with large files, caches (~30s, cached 5min). GET /disk/scan"""
        return self._get("/disk/scan", timeout=60)

    def delete_path(self, path: str, type: str = "file") -> dict:
        """Delete a file or directory. POST /disk/delete"""
        return self._post("/disk/delete", {"path": path, "type": type})

    def clean_cache(self, path: str) -> dict:
        """Clean all contents of a cache directory. POST /disk/clean-cache"""
        return self._post("/disk/clean-cache", {"path": path})

    def empty_trash(self) -> dict:
        """Empty the Trash directory. POST /disk/empty-trash"""
        return self._post("/disk/empty-trash")

    # ======================== Alerts & Guardian ========================

    def list_alerts(self) -> dict:
        """List recent pressure alerts (max 20). GET /alerts"""
        return self._get("/alerts")

    def get_guardian_log(self) -> dict:
        """Get memory guardian operation logs. GET /guardian"""
        return self._get("/guardian")

    # ======================== Reports ========================

    def list_reports(self, type: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        """List generated reports. GET /reports"""
        return self._get("/reports", {"type": type, "limit": limit, "offset": offset})

    def get_report(self, filename: str) -> dict:
        """Read a specific report (Markdown). GET /reports/{filename}"""
        return self._get(f"/reports/{filename}")

    # ======================== Context Manager ========================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"SystemMonitorClient(base_url={self.base_url!r})"

"""Base HTTP client for Workshop Core API modules.

All Workshop API clients inherit from BaseClient, which provides:
- Automatic space_id injection
- Standard error handling
- Configurable base URL via env or constructor

Usage:
    class MemvaultClient(BaseClient):
        def __init__(self, **kwargs):
            super().__init__(module="memvault", **kwargs)

        def recall(self, query: str, top_k: int = 5) -> list[dict]:
            return self._get("/search", {"q": query, "top_k": top_k})
"""

import os
from typing import Any

import httpx


class APIError(Exception):
    """Raised when the Core API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class ConnectionError(Exception):
    """Raised when the Core API is unreachable."""

    def __init__(self, url: str):
        self.url = url
        super().__init__(
            f"Cannot connect to Core API at {url}. "
            "Start server: cd core && uvicorn src.main:app --port 8801"
        )


class BaseClient:
    """HTTP client for a single Workshop Core API module.

    Args:
        module: API module name (e.g. "memvault", "finance").
        base_url: Core API URL. Defaults to CORE_API_URL env or localhost:8801.
        space_id: Space ID. Defaults to WORKSHOP_SPACE_ID env or "default".
        timeout: Default request timeout in seconds.
    """

    def __init__(
        self,
        module: str,
        base_url: str | None = None,
        space_id: str | None = None,
        timeout: float = 30,
    ):
        self.base_url = base_url or os.environ.get("CORE_API_URL", "http://localhost:8801")
        self.space_id = space_id or os.environ.get("WORKSHOP_SPACE_ID", "default")
        self.prefix = f"{self.base_url}/api/{module}"
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

    def _params(self, extra: dict | None = None) -> dict:
        p: dict[str, Any] = {"space_id": self.space_id}
        if extra:
            p.update({k: v for k, v in extra.items() if v is not None})
        return p

    def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            resp = self.client.get(f"{self.prefix}{path}", params=self._params(params))
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            raise ConnectionError(self.base_url)
        except httpx.HTTPStatusError as e:
            raise APIError(e.response.status_code, e.response.text[:500])

    def _post(self, path: str, body: dict | None = None, timeout: float | None = None) -> Any:
        try:
            resp = self.client.post(
                f"{self.prefix}{path}",
                json=body or {},
                params=self._params(),
                timeout=timeout or 60,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            raise ConnectionError(self.base_url)
        except httpx.HTTPStatusError as e:
            raise APIError(e.response.status_code, e.response.text[:500])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(prefix={self.prefix!r})"

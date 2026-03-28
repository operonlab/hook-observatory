"""Vision SDK — HTTP client for Vision station (port 10203).

Usage:
    from sdk_client.vision import VisionClient

    client = VisionClient()
    result = client.analyze("/path/to/photo.jpg", task="describe", engine="smolvlm")
    print(result["result"])
"""

import os
from typing import Any

import httpx

from ._base import APIError


class VisionClient:
    """HTTP client for Vision station (port 10203)."""

    def __init__(self, base_url: str | None = None, timeout: float = 120):
        self.base_url = (base_url or os.environ.get("VISION_URL", "http://127.0.0.1:10203")).rstrip(
            "/"
        )
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
            raise APIError(
                0,
                f"Cannot connect to Vision at {self.base_url}. "
                "Start server: cd stations/vision && .venv/bin/python3 main.py",
                module="vision",
            ) from None
        except httpx.HTTPStatusError as e:
            raise APIError(e.response.status_code, e.response.text[:500], module="vision") from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("GET", path, params=filtered).json()

    def _post(self, path: str, params: dict | None = None) -> Any:
        filtered = {k: v for k, v in params.items() if v is not None} if params else None
        return self._request("POST", path, params=filtered).json()

    # ======================== Health ========================

    def health(self) -> dict:
        return self._get("/health")

    def is_running(self) -> bool:
        try:
            self.health()
            return True
        except Exception:
            return False

    # ======================== Analyze ========================

    def analyze(
        self,
        file_path: str,
        task: str = "describe",
        engine: str = "apple",
        prompt: str | None = None,
    ) -> dict:
        """Analyze image with specified engine and task."""
        return self._post(
            "/analyze",
            params={"path": file_path, "task": task, "engine": engine, "prompt": prompt},
        )

    # ======================== Engines ========================

    def list_engines(self) -> dict:
        return self._get("/engines")

    # ======================== Context Manager ========================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"VisionClient(base_url={self.base_url!r})"

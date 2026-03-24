"""STT SDK — HTTP client for STT station (port 4108).

Usage:
    from workshop.clients.stt import STTClient

    client = STTClient()
    result = client.transcribe("/path/to/audio.m4a", language="zh-TW")
    print(result["text"])
"""

import os
from typing import Any

import httpx

from workshop.port_registry import get_url

from ._base import APIError


class STTClient:
    """HTTP client for STT station (port 4108)."""

    def __init__(self, base_url: str | None = None, timeout: float = 120):
        self.base_url = (base_url or os.environ.get("STT_URL", get_url("stt"))).rstrip("/")
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
                f"Cannot connect to STT at {self.base_url}. "
                "Start server: cd stations/stt && .venv/bin/python3 main.py",
                module="stt",
            ) from None
        except httpx.HTTPStatusError as e:
            raise APIError(e.response.status_code, e.response.text[:500], module="stt") from e

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

    # ======================== Transcribe ========================

    def transcribe(
        self,
        file_path: str,
        language: str = "zh-TW",
        engine: str = "apple",
        format: str = "json",
    ) -> dict | str:
        """Transcribe audio file. Returns dict for json, str for srt/vtt/text."""
        params = {
            "path": file_path,
            "language": language,
            "engine": engine,
            "format": format,
        }
        filtered = {k: v for k, v in params.items() if v is not None}
        resp = self._request("POST", "/transcribe", params=filtered)
        if format in ("srt", "vtt", "text"):
            return resp.text
        return resp.json()

    # ======================== Engines ========================

    def list_engines(self) -> dict:
        return self._get("/engines")

    # ======================== Context Manager ========================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"STTClient(base_url={self.base_url!r})"

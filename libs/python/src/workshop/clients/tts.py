"""TTS SDK — HTTP client for TTS station (port 10201).

Usage:
    from workshop.clients.tts import TTSClient

    client = TTSClient()
    result = client.synthesize("Hello world", engine="kokoro")
    print(result["audio_path"])
"""

import os
from typing import Any

import httpx

from ._base import APIError


class TTSClient:
    """HTTP client for TTS station (port 10201)."""

    def __init__(self, base_url: str | None = None, timeout: float = 120):
        self.base_url = (base_url or os.environ.get("TTS_URL", "http://127.0.0.1:10201")).rstrip(
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
                f"Cannot connect to TTS at {self.base_url}. "
                "Start server: cd stations/tts && .venv/bin/python3 main.py",
                module="tts",
            ) from None
        except httpx.HTTPStatusError as e:
            raise APIError(e.response.status_code, e.response.text[:500], module="tts") from e

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

    # ======================== Synthesize ========================

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        engine: str = "apple",
        format: str = "wav",
    ) -> dict:
        """Synthesize speech from text."""
        return self._post(
            "/synthesize",
            params={
                "text": text,
                "voice": voice,
                "speed": speed,
                "engine": engine,
                "format": format,
            },
        )

    # ======================== Voices ========================

    def list_voices(self, engine: str = "apple") -> dict:
        return self._get("/voices", params={"engine": engine})

    # ======================== Engines ========================

    def list_engines(self) -> dict:
        return self._get("/engines")

    # ======================== Context Manager ========================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"TTSClient(base_url={self.base_url!r})"

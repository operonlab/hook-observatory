"""OCR SDK — HTTP client for OCR station (port 4109).

Usage:
    from workshop.clients.ocr import OCRClient

    client = OCRClient()
    result = client.extract("/path/to/image.png", languages=["zh-Hant", "en"])
    print(result["text"])
"""

import os
from typing import Any

import httpx

from ._base import APIError


class OCRClient:
    """HTTP client for OCR station (port 4109)."""

    def __init__(self, base_url: str | None = None, timeout: float = 120):
        self.base_url = (
            base_url or os.environ.get("OCR_URL", "http://127.0.0.1:4109")
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
            raise APIError(
                0,
                f"Cannot connect to OCR at {self.base_url}. "
                "Start server: cd stations/ocr && .venv/bin/python3 main.py",
                module="ocr",
            ) from None
        except httpx.HTTPStatusError as e:
            raise APIError(e.response.status_code, e.response.text[:500], module="ocr") from e

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

    # ======================== Extract ========================

    def extract(
        self,
        file_path: str,
        languages: list[str] | None = None,
        engine: str = "apple",
        preprocess: str = "auto",
    ) -> dict:
        """Extract text from image or PDF."""
        lang_str = ",".join(languages) if languages else "zh-Hant,en"
        return self._post(
            "/extract",
            params={
                "path": file_path,
                "languages": lang_str,
                "engine": engine,
                "preprocess": preprocess,
            },
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
        return f"OCRClient(base_url={self.base_url!r})"

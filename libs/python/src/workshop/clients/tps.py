"""TPS SDK — HTTP client for TPS station (port 4114).

Usage:
    from workshop.clients.tps import TPSClient

    client = TPSClient()
    result = client.translate("Hello world", target_lang="zh-TW")
    print(result["text"])
"""

import os
from typing import Any

import httpx

from workshop.port_registry import get_url

from ._base import APIError


class TPSClient:
    """HTTP client for TPS station (port 4114)."""

    def __init__(self, base_url: str | None = None, timeout: float = 60):
        self.base_url = (
            base_url or os.environ.get("TPS_URL", get_url("tps"))
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
            resp = self.client.request(
                method, url, timeout=timeout or self._timeout, **kwargs
            )
            resp.raise_for_status()
            return resp
        except httpx.ConnectError:
            raise APIError(
                0,
                f"Cannot connect to TPS at {self.base_url}. "
                "Start server: cd stations/tps && .venv/bin/python3 main.py",
                module="tps",
            ) from None
        except httpx.HTTPStatusError as e:
            raise APIError(
                e.response.status_code, e.response.text[:500], module="tps"
            ) from e

    # ======================== Health ========================

    def health(self) -> dict:
        return self._request("GET", "/health").json()

    def is_running(self) -> bool:
        try:
            self.health()
            return True
        except Exception:
            return False

    # ======================== Translate ========================

    def translate(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = "zh-TW",
        provider: str | None = None,
    ) -> dict:
        """Translate text. Returns dict with text, provider, cached, etc."""
        body: dict[str, Any] = {
            "text": text,
            "source_lang": source_lang,
            "target_lang": target_lang,
        }
        if provider:
            body["provider"] = provider
        return self._request("POST", "/translate", json=body).json()

    def batch_translate(
        self,
        texts: list[str],
        source_lang: str = "auto",
        target_lang: str = "zh-TW",
    ) -> dict:
        """Batch translate texts. Returns dict with results list."""
        body = {
            "texts": texts,
            "source_lang": source_lang,
            "target_lang": target_lang,
        }
        return self._request("POST", "/translate/batch", json=body).json()

    # ======================== Usage ========================

    def usage(self) -> dict:
        """Get today's usage stats and budget."""
        return self._request("GET", "/usage").json()

    # ======================== Context Manager ========================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self) -> str:
        return f"TPSClient(base_url={self.base_url!r})"

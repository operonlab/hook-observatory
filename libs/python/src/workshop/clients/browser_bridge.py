"""Browser Bridge API client — Station at port 4106.

Provides chat, conversation management, session listing, and provider info
for the browser-bridge station.

Usage:
    from workshop.clients.browser_bridge import BrowserBridgeClient

    client = BrowserBridgeClient()
    providers = client.list_providers()
    result = client.chat(provider="grok", prompt="Hello!")
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ._base import APIConnectionError, APIError


class BrowserBridgeClient:
    """HTTP client for the browser-bridge station.

    Args:
        base_url: Station URL. Defaults to BRIDGE_URL env or http://127.0.0.1:4106.
        timeout: Default request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 120.0,
    ):
        self.base_url = base_url or os.environ.get("BRIDGE_URL", "http://127.0.0.1:4106")
        self._timeout = timeout
        self._client: httpx.Client | None = None

    @property
    def _http(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url.rstrip('/')}{path}"
        try:
            resp = self._http.request(method, url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.ConnectError:
            raise APIConnectionError(self.base_url) from None
        except httpx.HTTPStatusError as e:
            raise APIError(e.response.status_code, e.response.text[:500]) from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        return self._request(
            "GET", path,
            params={k: v for k, v in (params or {}).items() if v is not None},
        ).json()

    def _post(self, path: str, body: dict | None = None, timeout: float | None = None) -> Any:
        return self._request(
            "POST", path,
            json=body or {},
            timeout=timeout or self._timeout,
        ).json()

    # ------------------------------------------------------------------ #
    # Chat                                                                 #
    # ------------------------------------------------------------------ #

    def chat(
        self,
        provider: str,
        prompt: str,
        timeout: float | None = None,
        conversation_id: str | None = None,
    ) -> dict:
        """Send a prompt to a provider and get the response.

        Args:
            provider: Provider name (e.g. "grok", "notebooklm").
            prompt: User message text.
            timeout: Per-request timeout in seconds.
            conversation_id: Optional conversation ID for continuity.

        Returns:
            Response dict with status, provider, response, elapsed, etc.
        """
        body: dict[str, Any] = {"provider": provider, "prompt": prompt}
        if timeout:
            body["timeout"] = timeout
        if conversation_id:
            body["conversation_id"] = conversation_id
        return self._post("/api/bridge/chat", body, timeout=timeout or 180.0)

    # ------------------------------------------------------------------ #
    # Conversations                                                        #
    # ------------------------------------------------------------------ #

    def new_conversation(self, provider: str) -> dict:
        """Start a new conversation with a provider.

        Args:
            provider: Provider name.

        Returns:
            Response dict with status and conversation info.
        """
        return self._post("/api/bridge/new", {"provider": provider})

    def get_history(
        self,
        conversation_id: str | None = None,
        provider: str | None = None,
        limit: int = 50,
    ) -> dict:
        """Get conversation history.

        Args:
            conversation_id: Specific conversation (returns messages).
            provider: Filter by provider (returns conversations).
            limit: Max results.

        Returns:
            Dict with messages or conversations list.
        """
        params: dict[str, Any] = {"limit": limit}
        if conversation_id:
            params["conversation_id"] = conversation_id
        if provider:
            params["provider"] = provider
        return self._get("/api/bridge/history", params)

    # ------------------------------------------------------------------ #
    # Sessions                                                             #
    # ------------------------------------------------------------------ #

    def list_sessions(
        self,
        provider: str | None = None,
        active_only: bool = False,
        limit: int = 50,
    ) -> dict:
        """List browser sessions.

        Args:
            provider: Filter by provider.
            active_only: Only active sessions.
            limit: Max results.

        Returns:
            Dict with sessions list and stats.
        """
        params: dict[str, Any] = {"limit": limit}
        if provider:
            params["provider"] = provider
        if active_only:
            params["active_only"] = "true"
        return self._get("/api/bridge/sessions", params)

    # ------------------------------------------------------------------ #
    # Providers                                                            #
    # ------------------------------------------------------------------ #

    def list_providers(self) -> dict:
        """List available AI providers.

        Returns:
            Dict with providers list.
        """
        return self._get("/api/bridge/providers")

    # ------------------------------------------------------------------ #
    # Health                                                               #
    # ------------------------------------------------------------------ #

    def health(self) -> dict:
        """Check station health."""
        return self._get("/health")

    # ------------------------------------------------------------------ #
    # Context manager                                                      #
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            self._client.close()

    def __enter__(self) -> BrowserBridgeClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"BrowserBridgeClient(base_url={self.base_url!r})"

"""Browser Bridge API client — Station at port 4106.

Provides chat, conversation management, session listing, and provider info
for the browser-bridge station.

Usage:
    from workshop.clients.browser_bridge import BrowserBridgeClient

    client = BrowserBridgeClient()
    providers = client.providers()
    conv = client.new_conversation(provider="openai", model="gpt-4o")
    reply = client.chat(conversation_id=conv["id"], message="Hello!")
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class BrowserBridgeError(Exception):
    """Raised on Browser Bridge API errors."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"BrowserBridge error {status_code}: {detail}")


class BrowserBridgeConnectionError(Exception):
    """Raised when the browser-bridge station is unreachable."""

    def __init__(self, url: str):
        self.url = url
        super().__init__(
            f"Cannot connect to browser-bridge at {url}. "
            "Start station: cd stations/browser-bridge && python3 -m uvicorn main:app --port 4106"
        )


class BrowserBridgeClient:
    """HTTP client for the browser-bridge station.

    Args:
        base_url: Station URL. Defaults to BRIDGE_URL env or http://127.0.0.1:4106.
        timeout: Default request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 60.0,
    ):
        self.base_url = base_url or os.environ.get("BRIDGE_URL", "http://127.0.0.1:4106")
        self._timeout = timeout
        self._client: httpx.Client | None = None

    # ------------------------------------------------------------------ #
    # HTTP primitives                                                      #
    # ------------------------------------------------------------------ #

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
            raise BrowserBridgeConnectionError(self.base_url) from None
        except httpx.HTTPStatusError as e:
            raise BrowserBridgeError(e.response.status_code, e.response.text[:500]) from e

    def _get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params={k: v for k, v in (params or {}).items() if v is not None}).json()

    def _post(self, path: str, body: dict | None = None, timeout: float | None = None) -> Any:
        return self._request(
            "POST",
            path,
            json=body or {},
            timeout=timeout or self._timeout,
        ).json()

    def _delete(self, path: str) -> None:
        self._request("DELETE", path)

    # ------------------------------------------------------------------ #
    # Providers                                                            #
    # ------------------------------------------------------------------ #

    def providers(self) -> list[dict]:
        """List available LLM providers and their models.

        Returns:
            List of provider dicts with keys: id, name, models.
        """
        return self._get("/providers")

    # ------------------------------------------------------------------ #
    # Sessions                                                             #
    # ------------------------------------------------------------------ #

    def sessions(self) -> list[dict]:
        """List active browser sessions.

        Returns:
            List of session dicts with keys: id, created_at, provider.
        """
        return self._get("/sessions")

    # ------------------------------------------------------------------ #
    # Conversations                                                        #
    # ------------------------------------------------------------------ #

    def new_conversation(
        self,
        provider: str,
        model: str | None = None,
        session_id: str | None = None,
        system_prompt: str | None = None,
    ) -> dict:
        """Create a new conversation thread.

        Args:
            provider: Provider ID (e.g. "openai", "anthropic").
            model: Model identifier. Uses provider default if omitted.
            session_id: Reuse an existing browser session. Creates new one if omitted.
            system_prompt: Optional system prompt for the conversation.

        Returns:
            Conversation dict with keys: id, provider, model, created_at.
        """
        payload: dict[str, Any] = {"provider": provider}
        if model:
            payload["model"] = model
        if session_id:
            payload["session_id"] = session_id
        if system_prompt:
            payload["system_prompt"] = system_prompt
        return self._post("/conversations", payload)

    def history(self, conversation_id: str, limit: int = 50) -> list[dict]:
        """Retrieve message history for a conversation.

        Args:
            conversation_id: Conversation ID returned by new_conversation().
            limit: Maximum number of messages to return (default 50).

        Returns:
            List of message dicts with keys: role, content, timestamp.
        """
        return self._get(
            f"/conversations/{conversation_id}/history",
            params={"limit": limit},
        )

    def delete_conversation(self, conversation_id: str) -> None:
        """Delete a conversation and its message history.

        Args:
            conversation_id: Conversation ID to delete.
        """
        self._delete(f"/conversations/{conversation_id}")

    # ------------------------------------------------------------------ #
    # Chat                                                                 #
    # ------------------------------------------------------------------ #

    def chat(
        self,
        conversation_id: str,
        message: str,
        timeout: float = 120.0,
    ) -> dict:
        """Send a message and receive the assistant reply.

        Args:
            conversation_id: Conversation ID from new_conversation().
            message: User message text.
            timeout: Per-request timeout in seconds (default 120 for long LLM calls).

        Returns:
            Response dict with keys: role, content, usage (tokens), latency_ms.
        """
        return self._post(
            f"/conversations/{conversation_id}/chat",
            body={"message": message},
            timeout=timeout,
        )

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

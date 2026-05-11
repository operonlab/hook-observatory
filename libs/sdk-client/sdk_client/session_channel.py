"""Session Channel SDK client — cross-session messaging via Redis Streams.

Station client (not Core module). Uses x-local-key auth, port 10101.

Usage:
    from sdk_client.session_channel import SessionChannelClient

    client = SessionChannelClient()
    client.health()
    client.send_message("relay-activity", "✅ deploy done", tag="completed")
    msgs = client.read_messages("relay-activity", count=20)
    topics = client.list_topics()
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

import httpx

from sdk_client.port_registry import get_url

logger = logging.getLogger(__name__)

_DEFAULT_KEY = "change-me-in-production"


class SessionChannelClient:
    """HTTP client for session-channel station (port 10101).

    Args:
        base_url: Station URL. Defaults to SESSION_CHANNEL_URL env or port registry.
        local_key: Auth key. Defaults to SESSION_CHANNEL_KEY env.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str | None = None,
        local_key: str | None = None,
        timeout: float = 10,
    ):
        self.base_url = (
            base_url
            or os.environ.get("SESSION_CHANNEL_URL")
            or get_url("session-channel")
            or "http://localhost:10101"
        )
        self.local_key = local_key or os.environ.get("SESSION_CHANNEL_KEY", _DEFAULT_KEY)
        self.timeout = timeout
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=self.timeout,
                headers={
                    "x-local-key": self.local_key,
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _default_sender(self) -> str:
        pane = os.environ.get("TMUX_PANE", "")
        return pane if pane else f"sdk-{os.getpid()}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = self.client.request(method, url, json=json_body, params=params)
        except httpx.HTTPError as exc:
            logger.warning("session-channel %s %s failed: %s", method, path, exc)
            raise
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return None
        ctype = resp.headers.get("content-type", "")
        if "application/json" in ctype:
            return resp.json()
        return resp.text

    def health(self) -> dict:
        return self._request("GET", "/health") or {}

    def send_message(
        self,
        topic: str,
        text: str,
        sender: str | None = None,
        tag: str | None = None,
        priority: Literal["normal", "high"] = "normal",
    ) -> dict:
        body: dict[str, Any] = {
            "topic": topic,
            "text": text,
            "sender": sender or self._default_sender(),
            "priority": priority,
        }
        if tag:
            body["tag"] = tag
        return self._request("POST", "/api/messages", json_body=body) or {}

    def read_messages(self, topic: str, since: str = "0-0", count: int = 50) -> list[dict]:
        data = self._request(
            "GET",
            f"/api/messages/{topic}",
            params={"count": count, "since": since},
        )
        if isinstance(data, dict):
            return data.get("messages", [])
        return data or []

    def list_topics(self) -> list[dict]:
        data = self._request("GET", "/api/topics")
        if isinstance(data, dict):
            return data.get("topics", [])
        return data or []

    def __repr__(self) -> str:
        return f"SessionChannelClient(base_url={self.base_url!r})"


__all__ = ["SessionChannelClient"]

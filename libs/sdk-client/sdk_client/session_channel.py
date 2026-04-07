"""Session Channel SDK client — cross-session communication + task board.

Station client (not Core module). Uses x-local-key auth, port 10101.

Usage:
    from sdk_client.session_channel import SessionChannelClient

    client = SessionChannelClient()
    client.send("my-topic", "hello from SDK")
    client.board_publish("refactor-auth", [{"id": "t1", "desc": "Fix auth"}])
    client.board_show("refactor-auth")
    client.board_claim("refactor-auth", "t1")
    client.board_complete("refactor-auth", "t1", "done")
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

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
            base_url or os.environ.get("SESSION_CHANNEL_URL") or get_url("session-channel")
        )
        self._key = local_key or os.environ.get("SESSION_CHANNEL_KEY", _DEFAULT_KEY)
        self._timeout = timeout
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=self._timeout,
                headers={
                    "x-local-key": self._key,
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def _default_sender(self) -> str:
        pane = os.environ.get("TMUX_PANE", "")
        return pane if pane else f"sdk-{os.getpid()}"

    # ======================== Messages ========================

    def send(
        self,
        topic: str,
        text: str,
        *,
        sender: str = "",
        tag: str = "",
        priority: str = "normal",
    ) -> dict:
        """Send a message to a topic. POST /api/messages"""
        body: dict[str, Any] = {
            "topic": topic,
            "text": text,
            "sender": sender or self._default_sender(),
            "priority": priority,
        }
        if tag:
            body["tag"] = tag
        resp = self.client.post(f"{self.base_url}/api/messages", json=body)
        resp.raise_for_status()
        return resp.json()

    def read(self, topic: str, *, count: int = 50, since: str = "0-0") -> list[dict]:
        """Read messages from a topic. GET /api/messages/{topic}"""
        resp = self.client.get(
            f"{self.base_url}/api/messages/{topic}",
            params={"count": count, "since": since},
        )
        resp.raise_for_status()
        return resp.json().get("messages", [])

    def topics(self) -> list[dict]:
        """List active topics. GET /api/topics"""
        resp = self.client.get(f"{self.base_url}/api/topics")
        resp.raise_for_status()
        return resp.json().get("topics", [])

    def health(self) -> dict:
        """Check station health. GET /health"""
        resp = self.client.get(f"{self.base_url}/health")
        resp.raise_for_status()
        return resp.json()

    # ======================== Board ========================

    def board_publish(self, board_id: str, tasks: list[dict], *, sender: str = "") -> dict:
        """Publish a task board. tasks: [{id, desc, ...}]"""
        return self.send(
            topic=f"board:{board_id}",
            text=json.dumps({"tasks": tasks}),
            sender=sender,
            tag="publish",
            priority="high",
        )

    def board_show(self, board_id: str) -> dict:
        """Get board projection (tasks + claims + done). GET /api/board/{id}"""
        resp = self.client.get(f"{self.base_url}/api/board/{board_id}")
        resp.raise_for_status()
        return resp.json()

    def board_claim(self, board_id: str, task_id: str, *, pane: str = "") -> dict:
        """Atomically claim a task. POST /api/board/{id}/claim"""
        resp = self.client.post(
            f"{self.base_url}/api/board/{board_id}/claim",
            json={"task_id": task_id, "pane": pane or self._default_sender()},
        )
        resp.raise_for_status()
        return resp.json()

    def board_drop(self, board_id: str, task_id: str, *, pane: str = "") -> dict:
        """Release a claimed task. POST /api/board/{id}/drop"""
        resp = self.client.post(
            f"{self.base_url}/api/board/{board_id}/drop",
            json={"task_id": task_id, "pane": pane or self._default_sender()},
        )
        resp.raise_for_status()
        return resp.json()

    def board_complete(
        self, board_id: str, task_id: str, result: str = "done", *, sender: str = ""
    ) -> dict:
        """Mark a task as done. POST /api/messages with tag=done"""
        return self.send(
            topic=f"board:{board_id}",
            text=json.dumps({"task_id": task_id, "result": result}),
            sender=sender,
            tag="done",
        )

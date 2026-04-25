"""Session Channel SDK client — cross-session communication + task board.

Station client (not Core module). Uses x-local-key auth, port 10101.

This is the SoT for sdk-client distribution. The schema models below mirror
the SoT in `stations/session-channel/schemas.py` (Wave 1 worker-B). Keep them
in sync; future tooling may auto-sync.

Usage:
    from sdk_client.session_channel import SessionChannelClient, TaskPublish, TaskResult

    client = SessionChannelClient()
    client.health()
    client.publish_board("refactor-auth", [TaskPublish(id="t1", desc="Fix auth")])
    tasks = client.claim_task("refactor-auth", pane="%42", count=1)
    client.heartbeat("refactor-auth", "t1")
    client.progress("refactor-auth", "t1", percent=50, stage="impl")
    client.complete("refactor-auth", "t1", TaskResult(status="ok", payload={"msg": "done"}))
"""

from __future__ import annotations

import logging
import os
from enum import StrEnum
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from sdk_client.port_registry import get_url

logger = logging.getLogger(__name__)

_DEFAULT_KEY = "change-me-in-production"


# ============================================================
# Schema mirrors (SoT: stations/session-channel/schemas.py)
# ============================================================
# We mirror instead of import because:
# - station path is `stations/session-channel` (kebab) → not python-importable
# - sdk-client is independently distributable; cannot reverse-import station code
# Worker-B owns the station-side SoT; this mirror is updated alongside.


class TaskClass(StrEnum):
    SHORT = "short"
    LLM = "llm"
    VIDEO = "video"


class TaskPublish(BaseModel):
    """Task descriptor published to a board."""

    id: str
    desc: str
    task_class: TaskClass = TaskClass.SHORT
    required_caps: list[str] = Field(default_factory=list)
    assigned_to: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    priority: Literal["normal", "high"] = "normal"


class TaskResult(BaseModel):
    """Result payload reported on task completion."""

    status: Literal["ok", "error"] = "ok"
    payload: dict = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    tokens_used: int | None = None
    duration_ms: int | None = None
    error_message: str | None = None


class TaskProgress(BaseModel):
    """Mid-task progress update."""

    task_id: str
    percent: int
    stage: str = ""
    note: str = ""


class PaneAdvertise(BaseModel):
    """Pane capability advertisement."""

    pane_id: str
    cli_type: Literal["claude-code", "codex", "gemini", "unknown"] = "unknown"
    mcps: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    started_at: int
    last_seen: int


# ============================================================
# Client
# ============================================================


def _to_dict(obj: BaseModel | dict) -> dict:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return obj
    raise TypeError(f"Expected BaseModel or dict, got {type(obj).__name__}")


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

    # ---------- internal request helper ----------

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

    # ======================== Health ========================

    def health(self) -> dict:
        """GET /health"""
        return self._request("GET", "/health") or {}

    # ======================== Messages ========================

    def send_message(
        self,
        topic: str,
        text: str,
        sender: str | None = None,
        tag: str | None = None,
        priority: Literal["normal", "high"] = "normal",
    ) -> dict:
        """POST /api/messages — publish a free-form message to a topic."""
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
        """GET /api/messages/{topic}"""
        data = self._request(
            "GET",
            f"/api/messages/{topic}",
            params={"count": count, "since": since},
        )
        if isinstance(data, dict):
            return data.get("messages", [])
        return data or []

    def list_topics(self) -> list[dict]:
        """GET /api/topics"""
        data = self._request("GET", "/api/topics")
        if isinstance(data, dict):
            return data.get("topics", [])
        return data or []

    # ======================== Board ========================

    def publish_board(self, board_id: str, tasks: list[TaskPublish | dict]) -> dict:
        """POST /api/board/{id}/publish — declare tasks on a board.

        Accepts TaskPublish models or raw dicts.
        """
        body = {"tasks": [_to_dict(t) for t in tasks]}
        return self._request("POST", f"/api/board/{board_id}/publish", json_body=body) or {}

    def claim_task(self, board_id: str, pane: str, count: int = 1) -> list[dict]:
        """POST /api/board/{id}/claim — XREADGROUP-style atomic claim (W2-A).

        Returns list of claimed task descriptors.
        """
        body = {"pane": pane, "count": count}
        data = self._request("POST", f"/api/board/{board_id}/claim", json_body=body)
        if isinstance(data, dict):
            return data.get("tasks", [])
        return data or []

    def heartbeat(self, board_id: str, task_id: str) -> dict:
        """POST /api/board/{id}/heartbeat — extend ownership (W2-B XCLAIM)."""
        body = {"task_id": task_id}
        return self._request("POST", f"/api/board/{board_id}/heartbeat", json_body=body) or {}

    def progress(
        self,
        board_id: str,
        task_id: str,
        percent: int,
        stage: str = "",
        note: str = "",
    ) -> dict:
        """POST /api/board/{id}/progress — mid-task progress (W3-A)."""
        body = {"task_id": task_id, "percent": percent, "stage": stage, "note": note}
        return self._request("POST", f"/api/board/{board_id}/progress", json_body=body) or {}

    def complete(
        self,
        board_id: str,
        task_id: str,
        result: TaskResult | dict,
    ) -> dict:
        """POST /api/board/{id}/complete — finalize task with result (W3-C)."""
        body = {"task_id": task_id, "result": _to_dict(result)}
        return self._request("POST", f"/api/board/{board_id}/complete", json_body=body) or {}

    def drop_task(self, board_id: str, task_id: str, pane: str) -> dict:
        """POST /api/board/{id}/drop — release a claimed task."""
        body = {"task_id": task_id, "pane": pane}
        return self._request("POST", f"/api/board/{board_id}/drop", json_body=body) or {}

    def get_board(self, board_id: str) -> dict:
        """GET /api/board/{id} — full board projection."""
        return self._request("GET", f"/api/board/{board_id}") or {}

    def get_pending_by_pane(self, pane: str) -> list[dict]:
        """GET /api/board/pending — pending tasks claimed by `pane` (W2-C)."""
        data = self._request("GET", "/api/board/pending", params={"pane": pane})
        if isinstance(data, dict):
            return data.get("tasks", [])
        return data or []

    # ======================== Panes ========================

    def advertise(self, pane: PaneAdvertise | dict) -> dict:
        """POST /api/panes — advertise pane capabilities."""
        return self._request("POST", "/api/panes", json_body=_to_dict(pane)) or {}

    def delete_pane(self, pane_id: str) -> dict:
        """DELETE /api/panes/{pane_id}"""
        return self._request("DELETE", f"/api/panes/{pane_id}") or {}

    def list_panes(self) -> list[dict]:
        """GET /api/panes"""
        data = self._request("GET", "/api/panes")
        if isinstance(data, dict):
            return data.get("panes", [])
        return data or []

    def get_pane(self, pane_id: str) -> dict | None:
        """GET /api/panes/{pane_id} — None if 404."""
        try:
            return self._request("GET", f"/api/panes/{pane_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise

    def __repr__(self) -> str:
        return f"SessionChannelClient(base_url={self.base_url!r})"


__all__ = [
    "PaneAdvertise",
    "SessionChannelClient",
    "TaskClass",
    "TaskProgress",
    "TaskPublish",
    "TaskResult",
]

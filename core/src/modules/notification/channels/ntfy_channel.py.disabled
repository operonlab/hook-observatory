"""ntfy notification channel — push via self-hosted ntfy server."""

from __future__ import annotations

import asyncio
import json
from functools import partial

import structlog

from src.config import settings
from src.shared.capabilities import SupportsGrouping, SupportsPriority

from .base import BaseChannel

logger = structlog.get_logger()

# ntfy JSON API uses numeric priority: 1=min … 5=urgent
_NTFY_PRIORITY_MAP: dict[str, int] = {
    "urgent": 5,
    "high": 4,
    "default": 3,
    "low": 2,
    "min": 1,
}

# Map Workshop severity → ntfy named priority
_SEVERITY_TO_NTFY_PRIORITY: dict[str, str] = {
    "critical": "urgent",
    "warning": "high",
    "info": "default",
}


def _send_ntfy_sync(server: str, topic: str, payload: dict) -> bool:
    """Synchronous HTTP POST to ntfy server (runs in executor).

    Uses JSON body format to support UTF-8 titles (HTTP headers are latin-1 only).
    """
    import urllib.error
    import urllib.request

    url = server.rstrip("/")

    if not url.startswith(("http://", "https://")):
        logger.error("ntfy_invalid_scheme", url=url)
        return False

    try:
        ntfy_priority_name = payload.get("priority", "default")
        json_payload: dict = {
            "topic": topic,
            "title": payload.get("title", ""),
            "message": payload.get("body", ""),
            "priority": _NTFY_PRIORITY_MAP.get(ntfy_priority_name, 3),
        }
        if payload.get("tags"):
            json_payload["tags"] = payload["tags"].split(",")
        if payload.get("click"):
            json_payload["click"] = payload["click"]

        data = json.dumps(json_payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")  # noqa: S310
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        logger.error("ntfy_http_error", status=exc.code, url=url)
        return False
    except Exception as exc:
        logger.error("ntfy_send_error", error=str(exc))
        return False


class NtfyChannel(BaseChannel, SupportsGrouping, SupportsPriority):
    """Notification channel for ntfy (self-hosted push server)."""

    name = "ntfy"

    # SupportsGrouping
    def get_group(self, category: str) -> str:
        """Return the category as group identifier (unused by ntfy directly)."""
        return category or ""

    # SupportsPriority
    def map_severity(self, severity: str) -> str:
        """Map Workshop severity to ntfy named priority string."""
        return _SEVERITY_TO_NTFY_PRIORITY.get(severity, "default")

    async def _do_send(
        self,
        title: str,
        body: str,
        *,
        url: str = "",
        severity: str = "info",
        category: str = "",
    ) -> bool:
        server = getattr(settings, "ntfy_server_url", "")
        topic = getattr(settings, "ntfy_topic", "")

        if not server or not topic:
            logger.debug("ntfy_not_configured")
            return False

        payload: dict = {
            "title": title,
            "body": body,
            "priority": self.map_severity(severity),
        }
        if url:
            payload["click"] = url
        # category used as a tag for filtering in ntfy UI
        if category:
            payload["tags"] = category

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(_send_ntfy_sync, server, topic, payload))


# Auto-discovery hook — registry scans for this variable
CHANNEL = NtfyChannel()

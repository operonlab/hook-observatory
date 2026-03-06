"""ntfy adapter — push notifications via self-hosted ntfy server."""

from __future__ import annotations

import asyncio
from functools import partial

import structlog

from src.config import settings

logger = structlog.get_logger()

SEVERITY_TO_PRIORITY = {
    "critical": "urgent",
    "warning": "high",
    "info": "default",
}


def _send_ntfy_sync(server: str, topic: str, payload: dict) -> bool:
    """Synchronous HTTP POST to ntfy server (runs in executor)."""
    import urllib.error
    import urllib.request

    url = f"{server.rstrip('/')}/{topic}"

    if not url.startswith(("http://", "https://")):
        logger.error("ntfy_invalid_scheme", url=url)
        return False

    try:
        data = payload.get("body", "").encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")  # noqa: S310
        req.add_header("Title", payload.get("title", ""))
        req.add_header("Priority", payload.get("priority", "default"))
        if payload.get("tags"):
            req.add_header("Tags", payload["tags"])
        if payload.get("click"):
            req.add_header("Click", payload["click"])

        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status == 200
    except urllib.error.HTTPError as e:
        logger.error("ntfy_http_error", status=e.code, url=url)
        return False
    except Exception as e:
        logger.error("ntfy_send_error", error=str(e))
        return False


async def send_ntfy(
    title: str,
    body: str = "",
    *,
    url: str | None = None,
    severity: str = "info",
    tags: str | None = None,
) -> bool:
    """Send a push notification via ntfy.

    Args:
        title: Notification title.
        body: Notification body text.
        url: URL to open on click.
        severity: 'critical', 'warning', or 'info' — mapped to ntfy priority.
        tags: Comma-separated emoji tags (e.g. 'warning,skull').

    Returns:
        True if delivered successfully.
    """
    server = getattr(settings, "ntfy_server_url", "")
    topic = getattr(settings, "ntfy_topic", "")

    if not server or not topic:
        logger.debug("ntfy_not_configured")
        return False

    payload = {
        "title": title,
        "body": body,
        "priority": SEVERITY_TO_PRIORITY.get(severity, "default"),
    }
    if tags:
        payload["tags"] = tags
    if url:
        payload["click"] = url

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_send_ntfy_sync, server, topic, payload))

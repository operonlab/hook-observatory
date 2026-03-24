"""ntfy adapter — push notifications via self-hosted ntfy server."""

from __future__ import annotations

import asyncio
from functools import partial

import structlog

from src.config import settings

try:
    from workshop.retry import with_backoff

    _HAS_RETRY = True
except ImportError:
    _HAS_RETRY = False

logger = structlog.get_logger()

SEVERITY_TO_PRIORITY = {
    "critical": "urgent",
    "warning": "high",
    "info": "default",
}


def _send_ntfy_once(url: str, data: bytes) -> bool:
    """Single HTTP POST attempt to ntfy server (no retry)."""
    import urllib.request

    req = urllib.request.Request(url, data=data, method="POST")  # noqa: S310
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return resp.status == 200


def _is_transient_network_error(exc: Exception) -> bool:
    """URLError but NOT HTTPError (4xx/5xx are not transient)."""
    import urllib.error

    if isinstance(exc, urllib.error.HTTPError):
        return False
    return isinstance(exc, (urllib.error.URLError, TimeoutError, OSError))


def _send_ntfy_sync(server: str, topic: str, payload: dict) -> bool:
    """Synchronous HTTP POST to ntfy server (runs in executor), with retry.

    Uses JSON body format to support UTF-8 titles (HTTP headers are latin-1 only).
    """
    import json
    import urllib.error

    url = f"{server.rstrip('/')}"

    if not url.startswith(("http://", "https://")):
        logger.error("ntfy_invalid_scheme", url=url)
        return False

    try:
        json_payload = {
            "topic": topic,
            "title": payload.get("title", ""),
            "message": payload.get("body", ""),
            "priority": _PRIORITY_MAP.get(payload.get("priority", "default"), 3),
        }
        if payload.get("tags"):
            json_payload["tags"] = payload["tags"].split(",")
        if payload.get("click"):
            json_payload["click"] = payload["click"]

        data = json.dumps(json_payload).encode("utf-8")

        if _HAS_RETRY:
            return with_backoff(
                max_retries=3,
                base_delay=1.0,
                retryable=_is_transient_network_error,
            )(_send_ntfy_once)(url, data)
        else:
            return _send_ntfy_once(url, data)
    except urllib.error.HTTPError as e:
        logger.error("ntfy_http_error", status=e.code, url=url)
        return False
    except Exception as e:
        logger.error("ntfy_send_error", error=str(e))
        return False


# ntfy JSON API uses numeric priority: 1=min, 2=low, 3=default, 4=high, 5=urgent
_PRIORITY_MAP = {
    "urgent": 5,
    "high": 4,
    "default": 3,
    "low": 2,
    "min": 1,
}


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

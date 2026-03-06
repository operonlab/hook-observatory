"""Bark adapter — push notifications to iPhone via self-hosted Bark server."""

from __future__ import annotations

import asyncio
from functools import partial
from urllib.parse import quote

import structlog

from src.config import settings

logger = structlog.get_logger()


def _send_bark_sync(url: str) -> bool:
    """Synchronous HTTP GET to Bark server (runs in executor)."""
    import urllib.error
    import urllib.request

    if not url.startswith(("http://", "https://")):
        logger.error("bark_invalid_scheme", url=url)
        return False

    try:
        req = urllib.request.Request(url, method="GET")  # noqa: S310
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status == 200
    except urllib.error.HTTPError as e:
        logger.error("bark_http_error", status=e.code, url=url)
        return False
    except Exception as e:
        logger.error("bark_send_error", error=str(e))
        return False


async def send_bark(
    title: str,
    body: str = "",
    *,
    url: str | None = None,
    group: str | None = None,
    sound: str | None = None,
    level: str | None = None,
    icon: str | None = None,
) -> bool:
    """Send a push notification via Bark.

    Args:
        title: Notification title.
        body: Notification body text.
        url: URL to open on tap.
        group: Notification group name.
        sound: Sound name (e.g. 'alarm', 'bell', 'birdsong').
        level: 'active' (default), 'timeSensitive', or 'critical'.
        icon: Custom icon URL.

    Returns:
        True if delivered successfully.
    """
    server = getattr(settings, "bark_server_url", "")
    key = getattr(settings, "bark_device_key", "")

    if not server or not key:
        logger.debug("bark_not_configured")
        return False

    # Build Bark URL: {server}/{key}/{title}/{body}?params
    bark_url = f"{server.rstrip('/')}/{key}/{quote(title)}"
    if body:
        bark_url += f"/{quote(body)}"

    # Optional query params
    params = []
    if url:
        params.append(f"url={quote(url)}")
    if group:
        params.append(f"group={quote(group)}")
    if sound:
        params.append(f"sound={quote(sound)}")
    if level:
        params.append(f"level={quote(level)}")
    if icon:
        params.append(f"icon={quote(icon)}")
    if params:
        bark_url += "?" + "&".join(params)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_send_bark_sync, bark_url))

"""Bark notification channel — push to iPhone via self-hosted Bark server."""

from __future__ import annotations

import asyncio
from functools import partial
from urllib.parse import quote

import structlog

from src.config import settings
from src.shared.capabilities import SupportsGrouping, SupportsPriority

from .base import BaseChannel

logger = structlog.get_logger()

# Map Workshop severity → Bark notification level
_SEVERITY_TO_LEVEL: dict[str, str] = {
    "critical": "timeSensitive",
    "warning": "timeSensitive",
    "info": "active",
}


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
    except urllib.error.HTTPError as exc:
        logger.error("bark_http_error", status=exc.code, url=url)
        return False
    except Exception as exc:
        logger.error("bark_send_error", error=str(exc))
        return False


class BarkChannel(BaseChannel, SupportsGrouping, SupportsPriority):
    """Notification channel for Bark (iOS push via self-hosted server)."""

    name = "bark"

    # SupportsGrouping
    def get_group(self, category: str) -> str:
        """Return the category as the Bark group name."""
        return category or ""

    # SupportsPriority
    def map_severity(self, severity: str) -> str:
        """Map Workshop severity to Bark notification level."""
        return _SEVERITY_TO_LEVEL.get(severity, "active")

    async def _do_send(
        self,
        title: str,
        body: str,
        *,
        url: str = "",
        severity: str = "info",
        category: str = "",
    ) -> bool:
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
        params: list[str] = []
        if url:
            params.append(f"url={quote(url)}")
        group = self.get_group(category)
        if group:
            params.append(f"group={quote(group)}")
        level = self.map_severity(severity)
        if level:
            params.append(f"level={quote(level)}")
        if params:
            bark_url += "?" + "&".join(params)

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(_send_bark_sync, bark_url))


# Auto-discovery hook — registry scans for this variable
CHANNEL = BarkChannel()

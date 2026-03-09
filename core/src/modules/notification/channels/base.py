"""Base classes for notification channels."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

import structlog

logger = structlog.get_logger()


@runtime_checkable
class NotificationChannel(Protocol):
    """Protocol defining the notification channel contract."""

    name: str

    async def send(
        self,
        title: str,
        body: str,
        *,
        url: str = "",
        severity: str = "info",
        category: str = "",
    ) -> bool:
        """Send a notification.

        Args:
            title: Notification title.
            body: Notification body text.
            url: URL to open on tap/click.
            severity: 'critical', 'warning', or 'info'.
            category: Notification category for grouping.

        Returns:
            True if delivered successfully.
        """
        ...


class BaseChannel(ABC):
    """Abstract base channel with common error handling.

    Concrete channels must implement `_do_send()`.
    The public `send()` method wraps it with structured logging.
    """

    name: str = ""

    async def send(
        self,
        title: str,
        body: str,
        *,
        url: str = "",
        severity: str = "info",
        category: str = "",
    ) -> bool:
        """Send a notification with error handling and structured logging."""
        try:
            result = await self._do_send(
                title=title,
                body=body,
                url=url,
                severity=severity,
                category=category,
            )
            if result:
                logger.debug(
                    "channel_send_ok",
                    channel=self.name,
                    title=title,
                    severity=severity,
                )
            else:
                logger.warning(
                    "channel_send_failed",
                    channel=self.name,
                    title=title,
                    severity=severity,
                )
            return result
        except Exception as exc:
            logger.error(
                "channel_send_error",
                channel=self.name,
                title=title,
                error=str(exc),
            )
            return False

    @abstractmethod
    async def _do_send(
        self,
        title: str,
        body: str,
        *,
        url: str = "",
        severity: str = "info",
        category: str = "",
    ) -> bool:
        """Perform the actual send. Subclasses implement this."""
        ...

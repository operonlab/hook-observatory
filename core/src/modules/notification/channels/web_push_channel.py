"""Web Push notification channel — pywebpush wrapper with VAPID signing."""

from __future__ import annotations

import asyncio
import json
from functools import partial
from pathlib import Path

import structlog
from pywebpush import WebPushException, webpush

from src.config import settings
from src.shared.capabilities import SupportsIcon

from .base import BaseChannel

logger = structlog.get_logger()

# Map notification category to a specific icon path
_CATEGORY_ICONS: dict[str, str] = {
    "finance": "/icons/finance-192.png",
    "taskflow": "/icons/taskflow-192.png",
    "intelflow": "/icons/intelflow-192.png",
    "notification": "/icons/notification-192.png",
}
_DEFAULT_ICON = "/icons/icon-192.png"


def _load_vapid_private_key() -> str | None:
    """Load VAPID private key PEM from configured path or inline value."""
    key_path = getattr(settings, "vapid_private_key", "")
    if not key_path:
        return None
    p = Path(key_path).expanduser()
    if p.exists():
        return p.read_text()
    # Accept inline PEM string
    if "BEGIN" in key_path:
        return key_path
    return None


def _get_vapid_claims() -> dict:
    contact = getattr(settings, "vapid_contact", "mailto:admin@joneshong.com")
    return {"sub": contact}


def _send_push_sync(
    subscription_info: dict,
    payload: str,
    vapid_private_key: str,
    vapid_claims: dict,
) -> bool:
    """Synchronous webpush call (runs in executor)."""
    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=vapid_private_key,
            vapid_claims=vapid_claims,
        )
        return True
    except WebPushException as exc:
        # 404 or 410 = subscription expired/invalid — not an error worth retrying
        if hasattr(exc, "response") and exc.response is not None:
            status = exc.response.status_code
            if status in (404, 410):
                logger.info("push_subscription_expired", status=status)
                return False
        logger.error("webpush_error", error=str(exc))
        return False
    except Exception as exc:
        logger.error("webpush_unexpected_error", error=str(exc))
        return False


class WebPushChannel(BaseChannel, SupportsIcon):
    """Notification channel for Web Push (browser notifications via VAPID)."""

    name = "web_push"

    # SupportsIcon
    def get_icon_url(self, category: str) -> str:
        """Return icon URL for the given notification category."""
        return _CATEGORY_ICONS.get(category, _DEFAULT_ICON)

    async def _do_send(
        self,
        title: str,
        body: str,
        *,
        url: str = "",
        severity: str = "info",
        category: str = "",
    ) -> bool:
        """Single-recipient send — requires endpoint/p256dh/auth from push_data.

        For registry-based fire-and-forget dispatch this is a no-op placeholder.
        Actual delivery to multiple subscribers should use send_to_subscriptions().
        """
        logger.debug(
            "web_push_single_send_noop",
            hint="Use send_to_subscriptions() for DB-backed multi-recipient delivery",
        )
        return False

    async def send_to_subscriptions(
        self,
        subscriptions: list[dict],
        push_data: dict,
    ) -> tuple[int, int]:
        """Deliver a push notification to a list of subscription records.

        Args:
            subscriptions: List of dicts with keys: endpoint, p256dh, auth.
            push_data: Push payload dict (title, body, url, icon, badge, data, …).

        Returns:
            Tuple of (delivered_count, failed_count).
        """
        vapid_key = _load_vapid_private_key()
        if not vapid_key:
            logger.warning("vapid_key_not_configured")
            return 0, len(subscriptions)

        vapid_claims = _get_vapid_claims()
        loop = asyncio.get_running_loop()

        delivered = 0
        failed = 0

        tasks = []
        for sub in subscriptions:
            subscription_info = {
                "endpoint": sub["endpoint"],
                "keys": {
                    "p256dh": sub["p256dh"],
                    "auth": sub["auth"],
                },
            }
            tasks.append(
                loop.run_in_executor(
                    None,
                    partial(
                        _send_push_sync,
                        subscription_info=subscription_info,
                        payload=json.dumps(push_data),
                        vapid_private_key=vapid_key,
                        vapid_claims=vapid_claims,
                    ),
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if result is True:
                delivered += 1
            else:
                failed += 1

        logger.info(
            "web_push_batch_complete",
            delivered=delivered,
            failed=failed,
            total=len(subscriptions),
        )
        return delivered, failed


# Auto-discovery hook — registry scans for this variable
CHANNEL = WebPushChannel()

"""Web Push delivery — pywebpush wrapper with VAPID signing."""

import asyncio
import json
from functools import partial
from pathlib import Path

import structlog
from pywebpush import WebPushException, webpush

from src.config import settings

logger = structlog.get_logger()


def _load_vapid_private_key() -> str | None:
    """Load VAPID private key PEM from configured path."""
    key_path = getattr(settings, "vapid_private_key", "")
    if not key_path:
        return None
    p = Path(key_path).expanduser()
    if p.exists():
        return p.read_text()
    # If it looks like an inline PEM
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
    except WebPushException as e:
        # 404 or 410 = subscription expired/invalid
        if hasattr(e, "response") and e.response is not None:
            status = e.response.status_code
            if status in (404, 410):
                logger.info("push_subscription_expired", status=status)
                return False
        logger.error("webpush_error", error=str(e))
        return False
    except Exception as e:
        logger.error("webpush_unexpected_error", error=str(e))
        return False


async def send_push(
    endpoint: str,
    p256dh: str,
    auth: str,
    payload: dict,
) -> bool:
    """Send a single push notification. Returns True if delivered, False if expired/failed."""
    vapid_key = _load_vapid_private_key()
    if not vapid_key:
        logger.warning("vapid_key_not_configured")
        return False

    subscription_info = {
        "endpoint": endpoint,
        "keys": {"p256dh": p256dh, "auth": auth},
    }

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        partial(
            _send_push_sync,
            subscription_info=subscription_info,
            payload=json.dumps(payload),
            vapid_private_key=vapid_key,
            vapid_claims=_get_vapid_claims(),
        ),
    )

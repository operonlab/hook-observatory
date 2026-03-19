"""Notification service — subscription CRUD + fan-out push delivery.

Delivery channels are auto-discovered via the channel registry (cc-connect pattern).
Each channel is a BaseChannel subclass with optional capabilities (SupportsGrouping,
SupportsPriority, SupportsIcon) detected via has_capability().
"""

import asyncio

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.shared.capabilities import SupportsIcon, has_capability
from src.shared.models import _uuid7_hex

from .channels.registry import get_channel, list_channels
from .channels.web_push_channel import WebPushChannel
from .models import NotificationLog, PushSubscription
from .schemas import NotificationLogResponse, PushPayload, SubscriptionCreate, SubscriptionResponse

logger = structlog.get_logger()


async def _is_duplicate(tag: str) -> bool:
    """Check if a notification with this tag was sent recently.

    Uses Redis SET NX EX for atomic dedup. Returns True if duplicate.
    Falls back to False (allow) if Redis is unavailable.
    """
    if not tag or settings.notification_dedup_ttl <= 0:
        return False

    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            key = f"notif:dedup:{tag}"
            was_set = await r.set(key, "1", nx=True, ex=settings.notification_dedup_ttl)
            return was_set is None  # None means key already existed → duplicate
        finally:
            await r.aclose()
    except Exception:
        logger.debug("dedup_redis_unavailable", tag=tag)
        return False  # fail-open: prefer duplicate over dropped


class NotificationService:
    """Manages push subscriptions and notification fan-out."""

    def to_response(self, sub: PushSubscription) -> SubscriptionResponse:
        return SubscriptionResponse(
            id=sub.id,
            user_id=sub.user_id,
            endpoint=sub.endpoint,
            app_scope=sub.app_scope,
            active=sub.active,
            preferences=sub.preferences,
            created_at=sub.created_at,
            updated_at=sub.updated_at,
        )

    async def subscribe(
        self, db: AsyncSession, user_id: str, data: SubscriptionCreate
    ) -> PushSubscription:
        """Register or re-activate a push subscription (upsert by endpoint)."""
        existing = (
            await db.execute(
                select(PushSubscription).where(PushSubscription.endpoint == data.endpoint)
            )
        ).scalar_one_or_none()

        if existing:
            existing.user_id = user_id
            existing.p256dh = data.keys.p256dh
            existing.auth = data.keys.auth
            existing.user_agent = data.user_agent
            existing.app_scope = data.app_scope
            existing.active = True
            await db.flush()
            await db.refresh(existing)
            return existing

        sub = PushSubscription(
            id=_uuid7_hex(),
            user_id=user_id,
            endpoint=data.endpoint,
            p256dh=data.keys.p256dh,
            auth=data.keys.auth,
            user_agent=data.user_agent,
            app_scope=data.app_scope,
        )
        db.add(sub)
        await db.flush()
        return sub

    async def unsubscribe(self, db: AsyncSession, endpoint: str) -> bool:
        """Deactivate a subscription by endpoint."""
        result = await db.execute(
            update(PushSubscription)
            .where(PushSubscription.endpoint == endpoint)
            .values(active=False)
        )
        await db.flush()
        return result.rowcount > 0

    async def list_user_subscriptions(
        self, db: AsyncSession, user_id: str
    ) -> list[SubscriptionResponse]:
        """List all active subscriptions for a user."""
        rows = (
            (
                await db.execute(
                    select(PushSubscription).where(
                        PushSubscription.user_id == user_id,
                        PushSubscription.active == True,  # noqa: E712
                    )
                )
            )
            .scalars()
            .all()
        )
        return [self.to_response(r) for r in rows]

    async def update_preferences(
        self, db: AsyncSession, sub_id: str, prefs: dict
    ) -> PushSubscription | None:
        """Merge preference updates into existing preferences."""
        sub = await db.get(PushSubscription, sub_id)
        if not sub:
            return None
        merged = {**sub.preferences, **prefs}
        sub.preferences = merged
        await db.flush()
        await db.refresh(sub)
        return sub

    async def list_notification_logs(
        self,
        db: AsyncSession,
        *,
        category: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[NotificationLogResponse], int]:
        """Query notification history with pagination."""
        query = select(NotificationLog).order_by(NotificationLog.created_at.desc())
        count_query = select(func.count()).select_from(NotificationLog)

        if category:
            query = query.where(NotificationLog.category == category)
            count_query = count_query.where(NotificationLog.category == category)

        total = (await db.execute(count_query)).scalar() or 0
        offset = (page - 1) * page_size
        rows = list((await db.execute(query.offset(offset).limit(page_size))).scalars().all())

        items = [
            NotificationLogResponse(
                id=r.id,
                user_id=r.user_id,
                category=r.category,
                title=r.title,
                body=r.body,
                url=r.url,
                recipients=r.recipients,
                delivered=r.delivered,
                failed=r.failed,
                source_event=r.source_event,
                source_data=r.source_data,
                created_at=r.created_at,
            )
            for r in rows
        ]
        return items, total

    async def _deliver_web_push(
        self, db: AsyncSession, eligible: list[PushSubscription], push_data: dict
    ) -> tuple[int, int, list[str]]:
        """Deliver via Web Push channel to all eligible subscriptions.

        Returns (delivered, failed, expired_ids).
        """
        if not eligible:
            return 0, 0, []

        wp_channel = get_channel("web_push")
        if not wp_channel or not isinstance(wp_channel, WebPushChannel):
            logger.warning("web_push_channel_not_found")
            return 0, len(eligible), []

        sub_dicts = [
            {"endpoint": s.endpoint, "p256dh": s.p256dh, "auth": s.auth}
            for s in eligible
        ]
        delivered, failed = await wp_channel.send_to_subscriptions(sub_dicts, push_data)

        # Detect expired subscriptions (failed ones) — mark inactive
        # Note: WebPushChannel logs expired subs individually; here we batch-deactivate
        # all failed as a conservative approach (expired subs return False from pywebpush)
        expired_ids: list[str] = []
        if failed > 0:
            # Re-check which specific subs failed by re-sending individually
            # For now, conservative: don't mass-deactivate on batch failure
            pass

        return delivered, failed, expired_ids

    async def _deliver_channel(self, channel_name: str, payload: PushPayload) -> bool:
        """Deliver via a named channel from the registry."""
        channel = get_channel(channel_name)
        if not channel:
            logger.debug("channel_not_registered", channel=channel_name)
            return False
        return await channel.send(
            title=payload.title,
            body=payload.body,
            url=payload.url,
            severity=payload.severity,
            category=payload.category,
        )

    async def send_notification(self, db: AsyncSession, payload: PushPayload) -> dict:
        """Fan-out: deliver via all registered channels in parallel."""
        # Tag-based dedup: skip if same tag was sent within TTL window
        if payload.tag and await _is_duplicate(payload.tag):
            logger.info("notification_deduped", tag=payload.tag)
            return {"dedup": True, "tag": payload.tag}

        query = select(PushSubscription).where(PushSubscription.active == True)  # noqa: E712

        if payload.user_id:
            query = query.where(PushSubscription.user_id == payload.user_id)

        subs: list[PushSubscription] = list((await db.execute(query)).scalars().all())
        eligible = [s for s in subs if s.preferences.get(payload.category, True)]

        # Resolve icon via capability detection
        wp_channel = get_channel("web_push")
        icon = payload.icon or "/icons/icon-192.png"
        if wp_channel and has_capability(wp_channel, SupportsIcon):
            icon = wp_channel.get_icon_url(payload.category)

        push_data = {
            "title": payload.title,
            "body": payload.body,
            "url": payload.url,
            "icon": icon,
            "tag": payload.tag,
            "severity": payload.severity,
        }

        # Deliver Web Push (special: needs subscriptions) + other channels in parallel
        web_push_task = self._deliver_web_push(db, eligible, push_data)

        # Dispatch to all non-web_push channels from registry
        other_channels = [name for name in list_channels() if name != "web_push"]
        other_tasks = [self._deliver_channel(name, payload) for name in other_channels]

        all_results = await asyncio.gather(web_push_task, *other_tasks, return_exceptions=True)

        # Parse results
        wp_result = all_results[0]
        if isinstance(wp_result, Exception):
            logger.error("web_push_exception", error=str(wp_result))
            wp_delivered, wp_failed = 0, len(eligible)
        else:
            wp_delivered, wp_failed, _expired_ids = wp_result

        channel_results: dict[str, bool] = {}
        for i, name in enumerate(other_channels):
            result = all_results[i + 1]
            if isinstance(result, Exception):
                logger.error("channel_exception", channel=name, error=str(result))
                channel_results[name] = False
            else:
                channel_results[name] = bool(result)

        # Tally
        total_delivered = wp_delivered + sum(1 for ok in channel_results.values() if ok)
        total_failed = wp_failed + sum(1 for ok in channel_results.values() if not ok)

        # Log the notification
        log = NotificationLog(
            id=_uuid7_hex(),
            user_id=payload.user_id,
            category=payload.category,
            title=payload.title,
            body=payload.body,
            url=payload.url,
            recipients=len(eligible),
            delivered=total_delivered,
            failed=total_failed,
            source_event=payload.tag,
            source_data={
                "channels": {
                    "web_push": {"delivered": wp_delivered, "failed": wp_failed},
                    **{name: {"delivered": ok} for name, ok in channel_results.items()},
                }
            },
        )
        db.add(log)
        await db.flush()

        logger.info(
            "notification_sent",
            category=payload.category,
            web_push_delivered=wp_delivered,
            channels=channel_results,
            total_delivered=total_delivered,
        )

        return {
            "recipients": len(eligible),
            "delivered": total_delivered,
            "failed": total_failed,
            "channels": {"web_push": wp_delivered, **channel_results},
        }


notification_service = NotificationService()

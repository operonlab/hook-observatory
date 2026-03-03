"""Notification service — subscription CRUD + fan-out push delivery."""

import asyncio

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import _uuid7_hex

from .models import NotificationLog, PushSubscription
from .push import send_push
from .schemas import PushPayload, SubscriptionCreate, SubscriptionResponse

logger = structlog.get_logger()


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

    async def send_notification(self, db: AsyncSession, payload: PushPayload) -> dict:
        """Fan-out: send push notification to matching subscriptions."""
        query = select(PushSubscription).where(PushSubscription.active == True)  # noqa: E712

        if payload.user_id:
            query = query.where(PushSubscription.user_id == payload.user_id)

        subs: list[PushSubscription] = list((await db.execute(query)).scalars().all())

        # Filter by category preference
        eligible = [s for s in subs if s.preferences.get(payload.category, True)]

        push_data = {
            "title": payload.title,
            "body": payload.body,
            "url": payload.url,
            "icon": payload.icon or "/v2/icons/icon-192.png",
            "tag": payload.tag,
            "severity": payload.severity,
        }

        # Send in parallel
        tasks = [send_push(s.endpoint, s.p256dh, s.auth, push_data) for s in eligible]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        delivered = 0
        failed = 0
        expired_ids = []

        for i, result in enumerate(results):
            if result is True:
                delivered += 1
            else:
                failed += 1
                if result is False:
                    expired_ids.append(eligible[i].id)

        # Mark expired subscriptions as inactive
        if expired_ids:
            await db.execute(
                update(PushSubscription)
                .where(PushSubscription.id.in_(expired_ids))
                .values(active=False)
            )

        # Log the notification
        log = NotificationLog(
            id=_uuid7_hex(),
            user_id=payload.user_id,
            category=payload.category,
            title=payload.title,
            body=payload.body,
            url=payload.url,
            recipients=len(eligible),
            delivered=delivered,
            failed=failed,
            source_event=payload.tag,
        )
        db.add(log)
        await db.flush()

        logger.info(
            "push_notification_sent",
            category=payload.category,
            recipients=len(eligible),
            delivered=delivered,
            failed=failed,
        )

        return {"recipients": len(eligible), "delivered": delivered, "failed": failed}


notification_service = NotificationService()

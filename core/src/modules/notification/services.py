"""Notification service — subscription CRUD + fan-out push delivery."""

import asyncio

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.models import _uuid7_hex

from .adapters.bark import send_bark
from .adapters.ntfy import send_ntfy
from .models import NotificationLog, PushSubscription
from .push import send_push
from .schemas import NotificationLogResponse, PushPayload, SubscriptionCreate, SubscriptionResponse

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
        """Deliver via Web Push to all eligible subscriptions.

        Returns (delivered, failed, expired_ids).
        """
        if not eligible:
            return 0, 0, []

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

        if expired_ids:
            await db.execute(
                update(PushSubscription)
                .where(PushSubscription.id.in_(expired_ids))
                .values(active=False)
            )

        return delivered, failed, expired_ids

    async def _deliver_bark(self, payload: PushPayload) -> bool:
        """Deliver via Bark (iPhone push). Returns True if sent."""
        severity_to_level = {
            "critical": "timeSensitive",
            "warning": "timeSensitive",
            "info": "active",
        }
        try:
            return await send_bark(
                title=payload.title,
                body=payload.body,
                url=payload.url,
                group=payload.category,
                level=severity_to_level.get(payload.severity, "active"),
            )
        except Exception as e:
            logger.error("bark_delivery_error", error=str(e))
            return False

    async def _deliver_ntfy(self, payload: PushPayload) -> bool:
        """Deliver via ntfy (self-hosted push). Returns True if sent."""
        try:
            return await send_ntfy(
                title=payload.title,
                body=payload.body,
                url=payload.url,
                severity=payload.severity,
            )
        except Exception as e:
            logger.error("ntfy_delivery_error", error=str(e))
            return False

    async def send_notification(self, db: AsyncSession, payload: PushPayload) -> dict:
        """Fan-out: deliver via Web Push + Bark + ntfy in parallel."""
        query = select(PushSubscription).where(PushSubscription.active == True)  # noqa: E712

        if payload.user_id:
            query = query.where(PushSubscription.user_id == payload.user_id)

        subs: list[PushSubscription] = list((await db.execute(query)).scalars().all())
        eligible = [s for s in subs if s.preferences.get(payload.category, True)]

        push_data = {
            "title": payload.title,
            "body": payload.body,
            "url": payload.url,
            "icon": payload.icon or "/icons/icon-192.png",
            "tag": payload.tag,
            "severity": payload.severity,
        }

        # Deliver Web Push + Bark + ntfy in parallel
        web_push_task = self._deliver_web_push(db, eligible, push_data)
        bark_task = self._deliver_bark(payload)
        ntfy_task = self._deliver_ntfy(payload)

        (delivered, failed, _expired_ids), bark_ok, ntfy_ok = await asyncio.gather(
            web_push_task, bark_task, ntfy_task
        )

        # Log the notification
        total_delivered = delivered + (1 if bark_ok else 0) + (1 if ntfy_ok else 0)
        total_failed = failed + (0 if bark_ok else 1) + (0 if ntfy_ok else 1)

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
                    "web_push": {"delivered": delivered, "failed": failed},
                    "bark": {"delivered": bark_ok},
                    "ntfy": {"delivered": ntfy_ok},
                }
            },
        )
        db.add(log)
        await db.flush()

        logger.info(
            "notification_sent",
            category=payload.category,
            web_push_delivered=delivered,
            bark_ok=bark_ok,
            ntfy_ok=ntfy_ok,
            total_delivered=total_delivered,
        )

        return {
            "recipients": len(eligible),
            "delivered": total_delivered,
            "failed": total_failed,
            "channels": {"web_push": delivered, "bark": bark_ok, "ntfy": ntfy_ok},
        }


notification_service = NotificationService()

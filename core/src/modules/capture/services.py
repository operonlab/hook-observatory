"""CaptureService — CRUD + promote + completeness for the capture pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.shared.errors import BadRequestError, NotFoundError

from .models import Capture
from .registry import get_adapter
from .schemas import (
    CaptureCreate,
    CapturePromoteResult,
    CaptureResponse,
    CaptureStats,
    CaptureUpdate,
)


class CaptureService:
    async def create(
        self,
        db: AsyncSession,
        space_id: str,
        data: CaptureCreate,
        user_id: str | None = None,
        user_prefs: dict[str, Any] | None = None,
    ) -> Capture:
        adapter = get_adapter(data.module, data.entity_type)
        payload = dict(data.payload)

        # Apply smart defaults if adapter exists
        if adapter:
            payload = adapter.smart_defaults(payload, user_prefs or {})
            completeness = adapter.compute_completeness(payload)
            ttl_days = adapter.default_ttl_days
        else:
            completeness = 0.0
            ttl_days = 30

        capture = Capture(
            space_id=space_id,
            created_by=user_id,
            module=data.module,
            entity_type=data.entity_type,
            payload=payload,
            raw_input=data.raw_input,
            completeness=completeness,
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
        )
        db.add(capture)
        await db.flush()

        await event_bus.publish(
            Event(
                type="capture.created",
                data={
                    "capture_id": capture.id,
                    "module": capture.module,
                    "entity_type": capture.entity_type,
                    "completeness": capture.completeness,
                },
                source="capture",
                user_id=user_id,
            )
        )
        return capture

    async def get(self, db: AsyncSession, capture_id: str) -> Capture | None:
        stmt = select(Capture).where(
            Capture.id == capture_id, Capture.deleted_at.is_(None)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        module: str | None = None,
        entity_type: str | None = None,
        status: str = "pending",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Capture], int]:
        base = select(Capture).where(
            Capture.space_id == space_id,
            Capture.deleted_at.is_(None),
        )
        if module:
            base = base.where(Capture.module == module)
        if entity_type:
            base = base.where(Capture.entity_type == entity_type)
        if status:
            base = base.where(Capture.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_stmt)).scalar() or 0

        items_stmt = base.order_by(Capture.created_at.desc()).limit(limit).offset(offset)
        items = list((await db.execute(items_stmt)).scalars().all())
        return items, total

    async def update(
        self,
        db: AsyncSession,
        capture_id: str,
        data: CaptureUpdate,
        user_prefs: dict[str, Any] | None = None,
    ) -> Capture:
        capture = await self.get(db, capture_id)
        if not capture:
            raise NotFoundError("capture", capture_id)
        if capture.status != "pending":
            raise BadRequestError(f"Cannot update capture in status '{capture.status}'")

        if data.payload is not None:
            merged = {**capture.payload, **data.payload}
            adapter = get_adapter(capture.module, capture.entity_type)
            if adapter:
                merged = adapter.smart_defaults(merged, user_prefs or {})
                capture.completeness = adapter.compute_completeness(merged)
            capture.payload = merged
        if data.raw_input is not None:
            capture.raw_input = data.raw_input

        await db.flush()
        return capture

    async def delete(self, db: AsyncSession, capture_id: str) -> None:
        capture = await self.get(db, capture_id)
        if not capture:
            raise NotFoundError("capture", capture_id)
        capture.deleted_at = datetime.now(UTC)
        await db.flush()

    async def promote(
        self,
        db: AsyncSession,
        capture_id: str,
        user_id: str | None = None,
    ) -> CapturePromoteResult:
        capture = await self.get(db, capture_id)
        if not capture:
            raise NotFoundError("capture", capture_id)
        if capture.status != "pending":
            raise BadRequestError(f"Cannot promote capture in status '{capture.status}'")

        adapter = get_adapter(capture.module, capture.entity_type)
        if not adapter:
            raise BadRequestError(
                f"No adapter for {capture.module}.{capture.entity_type}"
            )

        missing = adapter.missing_fields(capture.payload)

        # The actual validation happens in the adapter's promote method
        try:
            promoted_id = await adapter.promote(
                dict(capture.payload),
                db,
                capture.space_id,
                user_id or capture.created_by,
            )
        except Exception as e:
            return CapturePromoteResult(
                success=False,
                capture_id=capture_id,
                missing_fields=missing,
                error=str(e),
            )

        capture.status = "promoted"
        capture.promoted_id = promoted_id
        capture.promoted_at = datetime.now(UTC)
        await db.flush()

        await event_bus.publish(
            Event(
                type="capture.promoted",
                data={
                    "capture_id": capture.id,
                    "module": capture.module,
                    "entity_type": capture.entity_type,
                    "promoted_id": promoted_id,
                },
                source="capture",
                user_id=user_id,
            )
        )

        return CapturePromoteResult(
            success=True,
            capture_id=capture_id,
            promoted_id=promoted_id,
        )

    async def stats(self, db: AsyncSession, space_id: str) -> CaptureStats:
        base = select(Capture).where(
            Capture.space_id == space_id,
            Capture.deleted_at.is_(None),
        )
        # Total
        total = (
            await db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0

        # By module
        mod_stmt = (
            select(Capture.module, func.count())
            .where(Capture.space_id == space_id, Capture.deleted_at.is_(None))
            .group_by(Capture.module)
        )
        by_module = dict((await db.execute(mod_stmt)).all())

        # By status
        status_stmt = (
            select(Capture.status, func.count())
            .where(Capture.space_id == space_id, Capture.deleted_at.is_(None))
            .group_by(Capture.status)
        )
        by_status = dict((await db.execute(status_stmt)).all())

        return CaptureStats(total=total, by_module=by_module, by_status=by_status)

    def to_response(self, capture: Capture) -> CaptureResponse:
        adapter = get_adapter(capture.module, capture.entity_type)
        missing = adapter.missing_fields(capture.payload) if adapter else []
        return CaptureResponse(
            id=capture.id,
            space_id=capture.space_id,
            module=capture.module,
            entity_type=capture.entity_type,
            payload=capture.payload,
            raw_input=capture.raw_input,
            completeness=capture.completeness,
            status=capture.status,
            promoted_id=capture.promoted_id,
            promoted_at=capture.promoted_at,
            expires_at=capture.expires_at,
            missing_fields=missing,
            created_at=capture.created_at,
            updated_at=capture.updated_at,
        )

    async def expire_stale(self, db: AsyncSession) -> int:
        """Expire captures past their TTL. Returns count of expired records."""
        now = datetime.now(UTC)
        stmt = (
            select(Capture)
            .where(
                Capture.status == "pending",
                Capture.expires_at.isnot(None),
                Capture.expires_at <= now,
                Capture.deleted_at.is_(None),
            )
        )
        result = await db.execute(stmt)
        captures = list(result.scalars().all())
        for c in captures:
            c.status = "expired"
        await db.flush()
        return len(captures)


capture_service = CaptureService()

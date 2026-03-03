"""Admin services — audit log queries.

This is the PUBLIC API of the admin module.
"""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.schemas import PaginatedResponse, PaginationParams

from .models import AuditLog
from .schemas import AuditLogResponse


class AuditService:
    """Query audit logs — read-only service."""

    def to_response(self, instance: AuditLog) -> AuditLogResponse:
        return AuditLogResponse(
            id=instance.id,
            user_id=instance.user_id,
            module=instance.module,
            entity_type=instance.entity_type,
            entity_id=instance.entity_id,
            space_id=instance.space_id,
            action=instance.action,
            changes=instance.changes,
            snapshot=instance.snapshot,
            created_at=instance.created_at,
        )

    async def list_logs(
        self,
        db: AsyncSession,
        pagination: PaginationParams | None = None,
        module: str | None = None,
        entity_type: str | None = None,
        user_id: str | None = None,
        space_id: str | None = None,
        action: str | None = None,
    ) -> PaginatedResponse[AuditLogResponse]:
        """Paginated audit log query with filters."""
        p = pagination or PaginationParams()
        base = select(AuditLog)
        if module:
            base = base.where(AuditLog.module == module)
        if entity_type:
            base = base.where(AuditLog.entity_type == entity_type)
        if user_id:
            base = base.where(AuditLog.user_id == user_id)
        if space_id:
            base = base.where(AuditLog.space_id == space_id)
        if action:
            base = base.where(AuditLog.action == action)

        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()

        q = (
            base.order_by(AuditLog.created_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows: Sequence[AuditLog] = (await db.execute(q)).scalars().all()
        return PaginatedResponse[AuditLogResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def get_entity_history(
        self,
        db: AsyncSession,
        module: str,
        entity_type: str,
        entity_id: str,
    ) -> list[AuditLogResponse]:
        """Get complete audit history for a specific entity."""
        q = (
            select(AuditLog)
            .where(
                AuditLog.module == module,
                AuditLog.entity_type == entity_type,
                AuditLog.entity_id == entity_id,
            )
            .order_by(AuditLog.created_at.asc())
        )
        rows = (await db.execute(q)).scalars().all()
        return [self.to_response(r) for r in rows]


audit_service = AuditService()

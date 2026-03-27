"""BaseCRUDService — simplified CRUD for paper-svc (no event bus, no audit trail)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.schemas import PaginatedResponse, PaginationParams

ModelT = TypeVar("ModelT")
CreateT = TypeVar("CreateT")
UpdateT = TypeVar("UpdateT")
ResponseT = TypeVar("ResponseT")


class BaseCRUDService(Generic[ModelT, CreateT, UpdateT, ResponseT]):
    """Template Method CRUD — subclass and override hooks.

    Simplified version for paper-svc: no event publishing, no audit trail.
    """

    model: type[ModelT]

    # --- Template Method hooks (override in subclass) ---

    def before_create(self, data: CreateT, **kwargs: Any) -> dict:
        """Transform create schema to model kwargs. Override for custom logic."""
        return data.model_dump() if hasattr(data, "model_dump") else dict(data)

    def after_create(self, instance: ModelT) -> None:
        """Post-create hook."""

    def before_update(self, instance: ModelT, data: UpdateT) -> dict:
        """Transform update schema before applying. Return dict of fields to set."""
        return data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data)

    def after_update(self, instance: ModelT, changes: dict) -> None:
        """Post-update hook."""

    def before_delete(self, instance: ModelT) -> None:
        """Pre-delete hook. Raise to abort deletion."""

    def after_delete(self, instance: ModelT) -> None:
        """Post-soft-delete hook."""

    def to_response(self, instance: ModelT) -> ResponseT:
        """Convert ORM instance to response schema. Must override."""
        raise NotImplementedError

    # --- Soft delete helpers ---

    def _has_soft_delete(self) -> bool:
        return hasattr(self.model, "deleted_at")

    # --- CRUD operations ---

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[ResponseT]:
        p = pagination or PaginationParams()
        base_filter = self.model.space_id == space_id  # type: ignore[attr-defined]
        count_q = select(func.count()).select_from(self.model).where(base_filter)
        if self._has_soft_delete():
            count_q = count_q.where(self.model.deleted_at == None)  # noqa: E711
        total = (await db.execute(count_q)).scalar_one()

        q = (
            select(self.model)
            .where(base_filter)
            .order_by(self.model.created_at.desc())  # type: ignore[attr-defined]
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        if self._has_soft_delete():
            q = q.where(self.model.deleted_at == None)  # noqa: E711
        rows: Sequence[ModelT] = (await db.execute(q)).scalars().all()
        return PaginatedResponse[ResponseT](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def get(self, db: AsyncSession, entity_id: str) -> ModelT | None:
        instance = await db.get(self.model, entity_id)
        if instance is None:
            return None
        if self._has_soft_delete() and getattr(instance, "deleted_at", None) is not None:
            return None
        return instance

    async def create(
        self, db: AsyncSession, space_id: str, data: CreateT, user_id: str | None = None
    ) -> ModelT:
        kwargs = self.before_create(data, space_id=space_id, user_id=user_id)
        kwargs["space_id"] = space_id
        if user_id:
            kwargs["created_by"] = user_id
        instance = self.model(**kwargs)  # type: ignore[call-arg]
        db.add(instance)
        await db.flush()
        self.after_create(instance)
        return instance

    async def update(
        self, db: AsyncSession, entity_id: str, data: UpdateT, user_id: str | None = None
    ) -> ModelT | None:
        instance = await self.get(db, entity_id)
        if not instance:
            return None

        update_data = self.before_update(instance, data)
        for key, value in update_data.items():
            setattr(instance, key, value)
        await db.flush()
        await db.refresh(instance)

        changes = update_data  # simplified — no diff tracking needed
        self.after_update(instance, changes)
        return instance

    async def delete(self, db: AsyncSession, entity_id: str, user_id: str | None = None) -> bool:
        instance = await self.get(db, entity_id)
        if not instance:
            return False

        self.before_delete(instance)

        if self._has_soft_delete():
            instance.deleted_at = datetime.now(UTC)  # type: ignore[attr-defined]
            await db.flush()
        else:
            await db.delete(instance)
            await db.flush()

        self.after_delete(instance)
        return True

"""BaseCRUDService — generic CRUD with Template Method hooks."""

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.schemas import PaginatedResponse, PaginationParams

ModelT = TypeVar("ModelT")
CreateT = TypeVar("CreateT")
UpdateT = TypeVar("UpdateT")
ResponseT = TypeVar("ResponseT")


class BaseCRUDService(Generic[ModelT, CreateT, UpdateT, ResponseT]):
    """Template Method CRUD — subclass and override hooks."""

    model: type[ModelT]

    # --- Template Method hooks (override in subclass) ---

    def before_create(self, data: CreateT, **kwargs: Any) -> dict:
        """Transform create schema to model kwargs. Override for custom logic."""
        return data.model_dump() if hasattr(data, "model_dump") else dict(data)

    def after_create(self, instance: ModelT) -> None:
        """Post-create hook (e.g., publish event)."""

    def to_response(self, instance: ModelT) -> ResponseT:
        """Convert ORM instance to response schema. Must override."""
        raise NotImplementedError

    # --- CRUD operations ---

    async def list(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[ResponseT]:
        p = pagination or PaginationParams()
        count_q = (
            select(func.count())
            .select_from(self.model)
            .where(
                self.model.space_id == space_id  # type: ignore[attr-defined]
            )
        )
        total = (await db.execute(count_q)).scalar_one()

        q = (
            select(self.model)
            .where(self.model.space_id == space_id)  # type: ignore[attr-defined]
            .order_by(self.model.created_at.desc())  # type: ignore[attr-defined]
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows: Sequence[ModelT] = (await db.execute(q)).scalars().all()
        return PaginatedResponse[ResponseT](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def get(self, db: AsyncSession, entity_id: str) -> ModelT | None:
        return await db.get(self.model, entity_id)

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

    async def update(self, db: AsyncSession, entity_id: str, data: UpdateT) -> ModelT | None:
        instance = await db.get(self.model, entity_id)
        if not instance:
            return None
        update_data = (
            data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data)
        )
        for key, value in update_data.items():
            setattr(instance, key, value)
        await db.flush()
        await db.refresh(instance)  # reload server-side onupdate fields (e.g. updated_at)
        return instance

    async def delete(self, db: AsyncSession, entity_id: str) -> bool:
        instance = await db.get(self.model, entity_id)
        if not instance:
            return False
        await db.delete(instance)
        await db.flush()
        return True

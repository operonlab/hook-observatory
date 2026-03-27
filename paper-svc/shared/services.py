"""BaseCRUDService — generic CRUD with Template Method hooks and soft delete.

Minimal adaptation from core/src/shared/services.py for paper-svc.
Key differences:
- No audit trail (no AuditLog dependency on admin module)
- No EventBus (no cross-module event publishing in standalone svc)
- Same CRUD interface preserved for API compatibility
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import PaginatedResponse, PaginationParams

ModelT = TypeVar("ModelT")
CreateT = TypeVar("CreateT")
UpdateT = TypeVar("UpdateT")
ResponseT = TypeVar("ResponseT")


def _serialize_value(value: Any) -> Any:
    """Convert a value to a JSON-safe representation."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    # numpy arrays from embeddings — skip large vectors
    if hasattr(value, "tolist"):
        items = value.tolist()
        if len(items) > 32:
            return f"<vector({len(items)})>"
        return items
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    return value


class BaseCRUDService(Generic[ModelT, CreateT, UpdateT, ResponseT]):
    """Template Method CRUD — subclass and override hooks.

    Standalone variant for paper-svc:
    - No audit trail (removed admin module dependency)
    - No EventBus auto-publish (removed event_bus dependency)
    - Same CRUD method signatures preserved for compatibility
    """

    model: type[ModelT]

    # --- Auto-event configuration (kept as stubs, no-ops in standalone) ---
    event_types: dict[str, str] = {}
    event_fields: tuple[str, ...] = ()
    event_id_alias: str = ""
    audit_module: str = ""
    audit_entity_type: str = ""

    # --- Template Method hooks (override in subclass) ---

    def before_create(self, data: CreateT, **kwargs: Any) -> dict:
        """Transform create schema to model kwargs."""
        return data.model_dump() if hasattr(data, "model_dump") else dict(data)

    def after_create(self, instance: ModelT) -> None:
        """Post-create hook — no-op in standalone svc (no EventBus)."""

    def before_update(self, instance: ModelT, data: UpdateT) -> dict:
        """Transform update schema before applying."""
        return data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data)

    def after_update(self, instance: ModelT, changes: dict) -> None:
        """Post-update hook — no-op in standalone svc."""

    def before_delete(self, instance: ModelT) -> None:
        """Pre-delete hook. Raise to abort deletion."""

    def after_delete(self, instance: ModelT) -> None:
        """Post-soft-delete hook — no-op in standalone svc."""

    def to_response(self, instance: ModelT) -> ResponseT:
        """Convert ORM instance to response schema. Must override."""
        raise NotImplementedError

    # --- Soft delete helpers ---

    def _has_soft_delete(self) -> bool:
        return hasattr(self.model, "deleted_at")

    def _get_entity_type(self) -> str:
        if self.audit_entity_type:
            return self.audit_entity_type
        return getattr(self.model, "__tablename__", self.model.__name__)

    def _snapshot(self, instance: ModelT) -> dict:
        """Serialize ORM instance to a JSON-safe dict."""
        result = {}
        mapper = getattr(instance.__class__, "__mapper__", None)
        if mapper is None:
            return result
        for col in mapper.columns:
            key = col.key
            value = getattr(instance, key, None)
            result[key] = _serialize_value(value)
        return result

    def _compute_diff(self, old_snapshot: dict, new_snapshot: dict) -> dict:
        """Compute field-level diff: {field: {old, new}} for changed fields."""
        diff = {}
        for key in old_snapshot:
            old_val = old_snapshot.get(key)
            new_val = new_snapshot.get(key)
            if old_val != new_val:
                diff[key] = {"old": old_val, "new": new_val}
        return diff

    # --- Lookup helpers ---

    name_column: str = "name"

    async def find_by_name(self, db: AsyncSession, space_id: str, name: str) -> ModelT | None:
        """Fuzzy name lookup. Returns first match or None."""
        col = getattr(self.model, self.name_column)
        q = select(self.model).where(
            self.model.space_id == space_id,  # type: ignore[attr-defined]
            col.ilike(f"%{name}%"),
        )
        if self._has_soft_delete():
            q = q.where(self.model.deleted_at == None)  # noqa: E711
        q = q.limit(1)
        return (await db.execute(q)).scalars().first()

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

        old_snapshot = self._snapshot(instance)
        update_data = self.before_update(instance, data)
        for key, value in update_data.items():
            setattr(instance, key, value)
        await db.flush()
        await db.refresh(instance)

        new_snapshot = self._snapshot(instance)
        changes = self._compute_diff(old_snapshot, new_snapshot)
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

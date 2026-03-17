"""BaseCRUDService — generic CRUD with Template Method hooks, audit trail, and soft delete."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.schemas import PaginatedResponse, PaginationParams

ModelT = TypeVar("ModelT")
CreateT = TypeVar("CreateT")
UpdateT = TypeVar("UpdateT")
ResponseT = TypeVar("ResponseT")


def _serialize_value(value: Any) -> Any:
    """Convert a value to a JSON-safe representation for audit logging."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    # numpy arrays from pgvector — skip large vectors to avoid audit log bloat
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

    Set `audit_module` to enable automatic audit trail recording.
    Set `audit_entity_type` to override the default (model.__tablename__).
    """

    model: type[ModelT]

    # --- Audit configuration (override in subclass) ---
    audit_module: str = ""
    audit_entity_type: str = ""

    # --- Template Method hooks (override in subclass) ---

    def before_create(self, data: CreateT, **kwargs: Any) -> dict:
        """Transform create schema to model kwargs. Override for custom logic."""
        return data.model_dump() if hasattr(data, "model_dump") else dict(data)

    def after_create(self, instance: ModelT) -> None:
        """Post-create hook (e.g., publish event)."""

    def before_update(self, instance: ModelT, data: UpdateT) -> dict:
        """Transform update schema before applying. Return dict of fields to set."""
        return data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data)

    def after_update(self, instance: ModelT, changes: dict) -> None:
        """Post-update hook. `changes` is the field-level diff."""

    def before_delete(self, instance: ModelT) -> None:
        """Pre-delete hook. Raise to abort deletion."""

    def after_delete(self, instance: ModelT) -> None:
        """Post-soft-delete hook."""

    def to_response(self, instance: ModelT) -> ResponseT:
        """Convert ORM instance to response schema. Must override."""
        raise NotImplementedError

    # --- Audit helpers ---

    def _get_entity_type(self) -> str:
        if self.audit_entity_type:
            return self.audit_entity_type
        return getattr(self.model, "__tablename__", self.model.__name__)

    def _snapshot(self, instance: ModelT) -> dict:
        """Serialize ORM instance to a JSON-safe dict for audit logging."""
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

    async def _record_audit(
        self,
        db: AsyncSession,
        action: str,
        entity_id: str,
        user_id: str | None = None,
        space_id: str | None = None,
        changes: dict | None = None,
        snapshot: dict | None = None,
    ) -> None:
        """Write an audit log entry within the current transaction."""
        if not self.audit_module:
            return
        from src.modules.admin.models import AuditLog
        from src.shared.models import _uuid7_hex

        log = AuditLog(
            id=_uuid7_hex(),
            user_id=user_id,
            module=self.audit_module,
            entity_type=self._get_entity_type(),
            entity_id=entity_id,
            space_id=space_id,
            action=action,
            changes=changes,
            snapshot=snapshot,
        )
        db.add(log)

    # --- Soft delete helpers ---

    def _has_soft_delete(self) -> bool:
        return hasattr(self.model, "deleted_at")

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
        if hasattr(self.model, "is_active"):
            q = q.where(self.model.is_active == True)  # noqa: E712
        if hasattr(self.model, "sort_order"):
            q = q.order_by(self.model.sort_order)
        q = q.limit(1)
        return (await db.execute(q)).scalars().first()

    async def ensure(
        self,
        db: AsyncSession,
        space_id: str,
        lookup: dict[str, Any],
        defaults: CreateT | None = None,
        user_id: str | None = None,
    ) -> tuple[ModelT, bool]:
        """Idempotent get-or-create. Returns (instance, created).

        Looks up by `lookup` fields within the space. If found, returns (existing, False).
        If not found and `defaults` provided, creates and returns (new, True).
        If not found and no defaults, raises NotFoundError.

        Inspired by acpx's idempotent 'sessions ensure' pattern.
        """
        from src.shared.errors import NotFoundError

        q = select(self.model).where(
            self.model.space_id == space_id,  # type: ignore[attr-defined]
        )
        for field, value in lookup.items():
            q = q.where(getattr(self.model, field) == value)
        if self._has_soft_delete():
            q = q.where(self.model.deleted_at == None)  # noqa: E711
        q = q.limit(1)

        existing = (await db.execute(q)).scalars().first()
        if existing is not None:
            return existing, False

        if defaults is None:
            entity_desc = ", ".join(f"{k}={v}" for k, v in lookup.items())
            raise NotFoundError(
                f"{self.model.__name__} not found: {entity_desc}",
                code="system.not_found",
            )

        created = await self.create(db, space_id, defaults, user_id=user_id)
        return created, True

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

    async def list_by_tags(
        self,
        db: AsyncSession,
        space_id: str,
        tags: list[str],
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[ResponseT]:
        """List entities matching ALL specified tags. Opt-in: requires model.tags column."""
        p = pagination or PaginationParams()
        base = select(self.model).where(
            self.model.space_id == space_id,  # type: ignore[attr-defined]
            self.model.tags.contains(tags),  # type: ignore[attr-defined]
        )
        if self._has_soft_delete():
            base = base.where(self.model.deleted_at == None)  # noqa: E711
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = (
            base.order_by(self.model.created_at.desc())  # type: ignore[attr-defined]
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
        instance = await db.get(self.model, entity_id)
        if instance is None:
            return None
        if self._has_soft_delete() and getattr(instance, "deleted_at", None) is not None:
            return None
        return instance

    async def get_including_deleted(self, db: AsyncSession, entity_id: str) -> ModelT | None:
        """Retrieve entity regardless of soft-delete status."""
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

        # Audit: record creation with full snapshot
        await self._record_audit(
            db,
            action="created",
            entity_id=instance.id,  # type: ignore[attr-defined]
            user_id=user_id,
            space_id=space_id,
            snapshot=self._snapshot(instance),
        )
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

        # Audit: record update with field-level diff
        if changes:
            space_id = getattr(instance, "space_id", None)
            await self._record_audit(
                db,
                action="updated",
                entity_id=entity_id,
                user_id=user_id,
                space_id=space_id,
                changes=changes,
            )
        return instance

    async def delete(self, db: AsyncSession, entity_id: str, user_id: str | None = None) -> bool:
        instance = await self.get(db, entity_id)
        if not instance:
            return False

        self.before_delete(instance)

        snapshot = self._snapshot(instance)
        space_id = getattr(instance, "space_id", None)

        if self._has_soft_delete():
            # Soft delete: set deleted_at timestamp
            instance.deleted_at = datetime.now(UTC)  # type: ignore[attr-defined]
            await db.flush()
        else:
            # Hard delete (no SoftDeleteMixin)
            await db.delete(instance)
            await db.flush()

        self.after_delete(instance)

        # Audit: record deletion with full snapshot
        await self._record_audit(
            db,
            action="deleted",
            entity_id=entity_id,
            user_id=user_id,
            space_id=space_id,
            snapshot=snapshot,
        )
        return True

    async def list_deleted(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[ResponseT]:
        """List soft-deleted entities (trash bin)."""
        if not self._has_soft_delete():
            return PaginatedResponse[ResponseT](items=[], total=0, page=1, page_size=20)
        p = pagination or PaginationParams()
        base_filter = [
            self.model.space_id == space_id,  # type: ignore[attr-defined]
            self.model.deleted_at != None,  # noqa: E711
        ]
        count_q = select(func.count()).select_from(self.model).where(*base_filter)
        total = (await db.execute(count_q)).scalar_one()

        q = (
            select(self.model)
            .where(*base_filter)
            .order_by(self.model.deleted_at.desc())  # type: ignore[attr-defined]
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

    async def restore(
        self, db: AsyncSession, entity_id: str, user_id: str | None = None
    ) -> ModelT | None:
        """Restore a soft-deleted entity."""
        if not self._has_soft_delete():
            return None
        instance = await db.get(self.model, entity_id)
        if not instance or getattr(instance, "deleted_at", None) is None:
            return None

        instance.deleted_at = None  # type: ignore[attr-defined]
        await db.flush()
        await db.refresh(instance)

        space_id = getattr(instance, "space_id", None)
        await self._record_audit(
            db,
            action="restored",
            entity_id=entity_id,
            user_id=user_id,
            space_id=space_id,
            snapshot=self._snapshot(instance),
        )
        return instance

    async def purge(self, db: AsyncSession, entity_id: str, user_id: str | None = None) -> bool:
        """Permanently delete (hard delete) an entity. Use for already-soft-deleted items."""
        instance = await db.get(self.model, entity_id)
        if not instance:
            return False

        snapshot = self._snapshot(instance)
        space_id = getattr(instance, "space_id", None)

        await db.delete(instance)
        await db.flush()

        await self._record_audit(
            db,
            action="purged",
            entity_id=entity_id,
            user_id=user_id,
            space_id=space_id,
            snapshot=snapshot,
        )
        return True

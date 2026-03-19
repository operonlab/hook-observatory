"""Shared query building helpers for space-scoped, soft-deletable models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, func, select

if TYPE_CHECKING:
    from src.shared.schemas import PaginationParams


def scoped_query[T](
    model: type[T],
    space_id: str,
    *,
    include_deleted: bool = False,
) -> Select[tuple[T]]:
    """Build a base SELECT scoped to a space with soft-delete filter.

    Usage::

        stmt = scoped_query(Position, space_id).where(Position.account_id == aid)
        result = await db.execute(stmt)
    """
    stmt = select(model).where(model.space_id == space_id)  # type: ignore[attr-defined]
    if not include_deleted and hasattr(model, "deleted_at"):
        stmt = stmt.where(model.deleted_at.is_(None))  # type: ignore[attr-defined]
    return stmt


async def paginated_count(
    db,
    stmt: Select,
) -> int:
    """Get total count for a query (for pagination)."""
    count_stmt = select(func.count()).select_from(stmt.subquery())
    result = await db.execute(count_stmt)
    return result.scalar() or 0


def apply_pagination[T](
    stmt: Select[tuple[T]],
    params: PaginationParams,
) -> Select[tuple[T]]:
    """Apply offset/limit pagination to a query."""
    return stmt.offset(params.offset).limit(params.limit)

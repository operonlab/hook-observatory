"""Tests for BaseCRUDService.ensure() — idempotent get-or-create.

Uses monkeypatching to bypass SQLAlchemy `select()` at the DB execute level.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.shared.errors import NotFoundError
from src.shared.services import BaseCRUDService

# ---------------------------------------------------------------------------
# Minimal fakes
# ---------------------------------------------------------------------------


class _ColumnMock:
    """Mimics SQLAlchemy column comparison (returns a truthy object for == ops)."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return True

    def __hash__(self):
        return id(self)


class FakeModel:
    """Minimal ORM model stub with class-level column-like attributes."""

    __name__ = "FakeModel"
    __tablename__ = "fake_models"
    space_id = _ColumnMock()
    deleted_at = _ColumnMock()
    name = _ColumnMock()

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeCreateSchema:
    def model_dump(self):
        return {"name": "thing-a"}


class FakeService(BaseCRUDService):
    model = FakeModel

    def to_response(self, instance):
        return instance


# ---------------------------------------------------------------------------
# DB session helpers
# ---------------------------------------------------------------------------


def _make_db(first_result=None):
    """Build a minimal AsyncSession mock."""
    scalars_mock = MagicMock()
    scalars_mock.first.return_value = first_result

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock

    db = AsyncMock()
    db.execute = AsyncMock(return_value=execute_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Tests — patch select() to bypass SQLAlchemy validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_returns_existing_record(monkeypatch):
    """ensure() returns (existing, False) when a matching record is found."""
    existing = FakeModel(space_id="space-1", name="thing-a")
    db = _make_db(first_result=existing)
    svc = FakeService()

    # Bypass SQLAlchemy's select() validation
    fake_query = MagicMock()
    fake_query.where.return_value = fake_query
    fake_query.limit.return_value = fake_query
    monkeypatch.setattr("src.shared.services.select", lambda *a: fake_query)

    instance, created = await svc.ensure(
        db,
        space_id="space-1",
        lookup={"name": "thing-a"},
    )

    assert instance is existing
    assert created is False
    # No create() should occur
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_creates_when_not_found(monkeypatch):
    """ensure() creates a new record and returns (new_instance, True)."""
    db = _make_db(first_result=None)
    svc = FakeService()

    fake_query = MagicMock()
    fake_query.where.return_value = fake_query
    fake_query.limit.return_value = fake_query
    monkeypatch.setattr("src.shared.services.select", lambda *a: fake_query)

    defaults = FakeCreateSchema()
    created_instance = FakeModel(space_id="space-1", name="thing-a", id="uuid-1")
    svc.create = AsyncMock(return_value=created_instance)

    instance, created = await svc.ensure(
        db,
        space_id="space-1",
        lookup={"name": "thing-a"},
        defaults=defaults,
        user_id="user-42",
    )

    assert instance is created_instance
    assert created is True
    svc.create.assert_awaited_once_with(db, "space-1", defaults, user_id="user-42")


@pytest.mark.asyncio
async def test_ensure_raises_not_found_when_no_defaults(monkeypatch):
    """ensure() raises NotFoundError when not found and no defaults provided."""
    db = _make_db(first_result=None)
    svc = FakeService()

    fake_query = MagicMock()
    fake_query.where.return_value = fake_query
    fake_query.limit.return_value = fake_query
    monkeypatch.setattr("src.shared.services.select", lambda *a: fake_query)

    with pytest.raises(NotFoundError) as exc_info:
        await svc.ensure(
            db,
            space_id="space-1",
            lookup={"name": "missing-thing"},
        )

    assert "missing-thing" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ensure_soft_delete_calls_where_three_times(monkeypatch):
    """ensure() adds deleted_at IS NULL filter when model supports soft-delete."""
    existing = FakeModel(space_id="space-1", name="thing-b", deleted_at=None)
    db = _make_db(first_result=existing)
    svc = FakeService()

    fake_query = MagicMock()
    fake_query.where.return_value = fake_query
    fake_query.limit.return_value = fake_query
    monkeypatch.setattr("src.shared.services.select", lambda *a: fake_query)

    instance, created = await svc.ensure(
        db,
        space_id="space-1",
        lookup={"name": "thing-b"},
    )

    assert instance is existing
    assert created is False
    # space_id where + name where + deleted_at where = 3 calls
    assert fake_query.where.call_count == 3


@pytest.mark.asyncio
async def test_ensure_no_soft_delete_skips_deleted_at(monkeypatch):
    """ensure() does NOT add deleted_at filter when model lacks soft-delete."""

    class HardDeleteModel:
        __name__ = "HardDeleteModel"
        __tablename__ = "hard_delete_models"
        space_id = _ColumnMock()
        name = _ColumnMock()
        # No `deleted_at` attribute → _has_soft_delete() is False

    class HardDeleteService(BaseCRUDService):
        model = HardDeleteModel

        def to_response(self, instance):
            return instance

    existing = MagicMock()
    db = _make_db(first_result=existing)
    svc = HardDeleteService()

    fake_query = MagicMock()
    fake_query.where.return_value = fake_query
    fake_query.limit.return_value = fake_query
    monkeypatch.setattr("src.shared.services.select", lambda *a: fake_query)

    instance, created = await svc.ensure(
        db,
        space_id="space-2",
        lookup={"name": "item"},
    )

    assert instance is existing
    assert created is False
    # space_id where + name where = 2 calls (no deleted_at)
    assert fake_query.where.call_count == 2
    assert svc._has_soft_delete() is False

"""Adversary test — §5 Service-layer invalidate_block / restore_block contract.

Validates (real PG):
- invalidate_block(db, block_id) with no superseded_by_id → superseded_by=None
- invalidate_block(db, block_id, reason='manual', superseded_by_id=None) backward-compat
- invalidate_block returns mutated MemoryBlock (not None)
- restore_block(db, block_id) clears invalid_at, superseded_by, invalidation_reason
- restore_block returns mutated MemoryBlock
- restore_block(db, not_found_id) returns None

Also:
- §1.1 list() include_invalid param: True includes invalidated, False excludes
- §1.1 list_by_tags() and list_by_type() respect include_invalid

DB-required tests use skipif guard.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_WORKTREE_CORE = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
_WORKTREE_CORE_SRC = os.path.join(_WORKTREE_CORE, "src")
sys.path = [
    p for p in sys.path if "/workshop/" not in p or ".claude/worktrees/" in p or "/.venv/" in p
]
sys.path.insert(0, _WORKTREE_CORE_SRC)
sys.path.insert(0, _WORKTREE_CORE)
for libname in (
    "text-ops",
    "audio-ops",
    "image-ops",
    "kg-ops",
    "sdk-client",
    "tmux-lib",
    "video-ops",
):
    p = f"/Users/joneshong/workshop/libs/{libname}"
    if p not in sys.path:
        sys.path.append(p)

# DB-dependent guard
pytest.importorskip("sqlalchemy")
pytest.importorskip("psycopg")

from sqlalchemy import select  # noqa: E402

from shared.database import async_session_factory  # noqa: E402
from src.modules.memvault.models import MemoryBlock  # noqa: E402
from src.modules.memvault.services import memory_block_service  # noqa: E402


def _uid() -> str:
    return uuid.uuid4().hex[:16]


async def _insert_block(space_id: str, **kwargs) -> MemoryBlock:
    """Insert a MemoryBlock and return it."""
    block_id = _uid()
    block = MemoryBlock(
        id=block_id,
        space_id=space_id,
        content=kwargs.get("content", f"test content {block_id}"),
        block_type=kwargs.get("block_type", "knowledge"),
        tags=kwargs.get("tags", []),
        created_at=kwargs.get("created_at", datetime.now(UTC)),
    )
    for k, v in kwargs.items():
        if k not in ("content", "block_type", "tags", "created_at"):
            setattr(block, k, v)
    async with async_session_factory() as db:
        db.add(block)
        await db.commit()
    return block


async def _delete_blocks(ids: list[str]) -> None:
    """Hard-delete blocks by IDs."""
    async with async_session_factory() as db:
        for bid in ids:
            row = (
                await db.execute(select(MemoryBlock).where(MemoryBlock.id == bid))
            ).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
                await db.commit()


# ── §5.1 invalidate_block returns block (not None) ──────────────────────────


@pytest.mark.asyncio
async def test_invalidate_block_returns_block():
    """invalidate_block must return the mutated MemoryBlock, not None."""
    space_id = f"adv-svc-{_uid()}"
    block = await _insert_block(space_id)
    try:
        async with async_session_factory() as db:
            result = await memory_block_service.invalidate_block(db, block.id)
        assert result is not None, "invalidate_block must return the block"
        assert hasattr(result, "invalid_at") or isinstance(result, dict), (
            f"Unexpected return type: {type(result)}"
        )
    finally:
        await _delete_blocks([block.id])


@pytest.mark.asyncio
async def test_invalidate_block_sets_invalid_at():
    """After invalidate_block, block.invalid_at must be set to approximately now."""
    space_id = f"adv-svc-{_uid()}"
    block = await _insert_block(space_id)
    now_before = datetime.now(UTC)
    try:
        async with async_session_factory() as db:
            result = await memory_block_service.invalidate_block(db, block.id)
        now_after = datetime.now(UTC)

        # Get the updated block from DB
        async with async_session_factory() as db:
            updated = (
                await db.execute(select(MemoryBlock).where(MemoryBlock.id == block.id))
            ).scalar_one_or_none()

        assert updated is not None
        assert updated.invalid_at is not None, "invalid_at must be set after invalidate_block"
        assert now_before <= updated.invalid_at <= now_after, (
            f"invalid_at {updated.invalid_at} must be between {now_before} and {now_after}"
        )
    finally:
        await _delete_blocks([block.id])


@pytest.mark.asyncio
async def test_invalidate_block_no_superseded_by_sets_null():
    """When superseded_by_id is not provided, block.superseded_by MUST be None."""
    space_id = f"adv-svc-{_uid()}"
    block = await _insert_block(space_id)
    try:
        async with async_session_factory() as db:
            await memory_block_service.invalidate_block(db, block.id)

        async with async_session_factory() as db:
            updated = (
                await db.execute(select(MemoryBlock).where(MemoryBlock.id == block.id))
            ).scalar_one_or_none()

        assert updated is not None
        assert updated.superseded_by is None, (
            f"superseded_by must be None when not provided; got {updated.superseded_by}"
        )
    finally:
        await _delete_blocks([block.id])


@pytest.mark.asyncio
async def test_invalidate_block_with_reason_sets_reason():
    """invalidate_block with reason='manual' sets invalidation_reason."""
    space_id = f"adv-svc-{_uid()}"
    block = await _insert_block(space_id)
    try:
        async with async_session_factory() as db:
            await memory_block_service.invalidate_block(db, block.id, reason="manual")

        async with async_session_factory() as db:
            updated = (
                await db.execute(select(MemoryBlock).where(MemoryBlock.id == block.id))
            ).scalar_one_or_none()

        assert updated is not None
        assert updated.invalidation_reason == "manual", (
            f"invalidation_reason must be 'manual'; got {updated.invalidation_reason!r}"
        )
    finally:
        await _delete_blocks([block.id])


@pytest.mark.asyncio
async def test_invalidate_block_with_superseded_by_id():
    """When superseded_by_id is provided, block.superseded_by is set."""
    space_id = f"adv-svc-{_uid()}"
    old_block = await _insert_block(space_id)
    new_block = await _insert_block(space_id, content="new block content")
    try:
        async with async_session_factory() as db:
            await memory_block_service.invalidate_block(
                db, old_block.id, reason="superseded", superseded_by_id=new_block.id
            )

        async with async_session_factory() as db:
            updated = (
                await db.execute(select(MemoryBlock).where(MemoryBlock.id == old_block.id))
            ).scalar_one_or_none()

        assert updated is not None
        assert updated.superseded_by == new_block.id, (
            f"superseded_by must be {new_block.id}; got {updated.superseded_by}"
        )
    finally:
        await _delete_blocks([old_block.id, new_block.id])


# ── §5.2 restore_block ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restore_block_clears_invalid_at():
    """restore_block must set invalid_at=None."""
    space_id = f"adv-svc-{_uid()}"
    block = await _insert_block(space_id, invalid_at=datetime.now(UTC))
    try:
        async with async_session_factory() as db:
            result = await memory_block_service.restore_block(db, block.id)
        assert result is not None, "restore_block must return the block"

        async with async_session_factory() as db:
            updated = (
                await db.execute(select(MemoryBlock).where(MemoryBlock.id == block.id))
            ).scalar_one_or_none()

        assert updated is not None
        assert updated.invalid_at is None, (
            f"After restore_block, invalid_at must be None; got {updated.invalid_at}"
        )
    finally:
        await _delete_blocks([block.id])


@pytest.mark.asyncio
async def test_restore_block_clears_superseded_by():
    """restore_block must set superseded_by=None."""
    space_id = f"adv-svc-{_uid()}"
    other = await _insert_block(space_id)
    block = await _insert_block(
        space_id,
        invalid_at=datetime.now(UTC),
        superseded_by=other.id,
        invalidation_reason="superseded",
    )
    try:
        async with async_session_factory() as db:
            await memory_block_service.restore_block(db, block.id)

        async with async_session_factory() as db:
            updated = (
                await db.execute(select(MemoryBlock).where(MemoryBlock.id == block.id))
            ).scalar_one_or_none()

        assert updated is not None
        assert updated.superseded_by is None, (
            f"After restore_block, superseded_by must be None; got {updated.superseded_by}"
        )
        assert updated.invalidation_reason is None, (
            f"After restore_block, invalidation_reason must be None; "
            f"got {updated.invalidation_reason}"
        )
    finally:
        await _delete_blocks([block.id, other.id])


@pytest.mark.asyncio
async def test_restore_block_not_found_returns_none():
    """restore_block(db, nonexistent_id) must return None, not raise."""
    async with async_session_factory() as db:
        result = await memory_block_service.restore_block(db, "nonexistent-id-xyz")
    assert result is None, f"restore_block for missing id must return None; got {result}"


# ── §1.1 list() include_invalid ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_blocks_default_excludes_invalid():
    """list() default (include_invalid=False) must not return invalidated blocks."""
    space_id = f"adv-svc-{_uid()}"
    active = await _insert_block(space_id, content="active block")
    invalid = await _insert_block(space_id, content="invalid block", invalid_at=datetime.now(UTC))
    try:
        async with async_session_factory() as db:
            resp = await memory_block_service.list(db, space_id)

        ids = {item.id for item in resp.items}
        assert active.id in ids, "Active block must appear in list()"
        assert invalid.id not in ids, "Invalidated block must not appear in list() by default"
    finally:
        await _delete_blocks([active.id, invalid.id])


@pytest.mark.asyncio
async def test_list_blocks_include_invalid_true_shows_invalid():
    """list(include_invalid=True) must include invalidated blocks."""
    space_id = f"adv-svc-{_uid()}"
    invalid = await _insert_block(space_id, content="invalid block", invalid_at=datetime.now(UTC))
    try:
        async with async_session_factory() as db:
            resp = await memory_block_service.list(db, space_id, include_invalid=True)

        ids = {item.id for item in resp.items}
        assert invalid.id in ids, (
            "Invalidated block must appear when include_invalid=True"
        )
    finally:
        await _delete_blocks([invalid.id])


@pytest.mark.asyncio
async def test_list_blocks_include_invalid_never_shows_soft_deleted():
    """Even include_invalid=True must NEVER return soft-deleted (deleted_at) blocks."""
    space_id = f"adv-svc-{_uid()}"
    deleted = await _insert_block(
        space_id,
        content="soft deleted block",
        deleted_at=datetime.now(UTC),
    )
    try:
        async with async_session_factory() as db:
            resp = await memory_block_service.list(db, space_id, include_invalid=True)

        ids = {item.id for item in resp.items}
        assert deleted.id not in ids, (
            "Soft-deleted blocks must never appear even with include_invalid=True"
        )
    finally:
        await _delete_blocks([deleted.id])


@pytest.mark.asyncio
async def test_list_by_tags_respects_include_invalid():
    """list_by_tags with include_invalid=False excludes invalid blocks."""
    space_id = f"adv-svc-{_uid()}"
    tag = f"adv-tag-{_uid()}"
    active = await _insert_block(space_id, content="active tag block", tags=[tag])
    invalid = await _insert_block(
        space_id, content="invalid tag block", tags=[tag], invalid_at=datetime.now(UTC)
    )
    try:
        async with async_session_factory() as db:
            resp_default = await memory_block_service.list_by_tags(db, space_id, [tag])
        ids_default = {item.id for item in resp_default.items}
        assert invalid.id not in ids_default, "list_by_tags must exclude invalid by default"

        async with async_session_factory() as db:
            resp_with = await memory_block_service.list_by_tags(
                db, space_id, [tag], include_invalid=True
            )
        ids_with = {item.id for item in resp_with.items}
        assert invalid.id in ids_with, "list_by_tags include_invalid=True must show invalid"
    finally:
        await _delete_blocks([active.id, invalid.id])


@pytest.mark.asyncio
async def test_list_by_type_respects_include_invalid():
    """list_by_type with include_invalid=False excludes invalid blocks."""
    space_id = f"adv-svc-{_uid()}"
    btype = "skill"
    active = await _insert_block(space_id, content="active skill block", block_type=btype)
    invalid = await _insert_block(
        space_id, content="invalid skill block", block_type=btype, invalid_at=datetime.now(UTC)
    )
    try:
        async with async_session_factory() as db:
            resp_default = await memory_block_service.list_by_type(db, space_id, btype)
        ids_default = {item.id for item in resp_default.items}
        assert invalid.id not in ids_default, "list_by_type must exclude invalid by default"

        async with async_session_factory() as db:
            resp_with = await memory_block_service.list_by_type(
                db, space_id, btype, include_invalid=True
            )
        ids_with = {item.id for item in resp_with.items}
        assert invalid.id in ids_with, (
            "list_by_type include_invalid=True must show invalid blocks"
        )
    finally:
        await _delete_blocks([active.id, invalid.id])

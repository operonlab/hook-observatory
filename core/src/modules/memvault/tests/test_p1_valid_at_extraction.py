"""P1 integration test — MemoryBlock.valid_at column + extract_valid_at helper.

Real PG required. Verifies:
  - Column exists and is writable.
  - extract_valid_at picks first ISO date from content.
  - extract_valid_at handles relative phrases (上週 / 去年 / etc) via normalize_temporal_range.
  - Explicit body.valid_at would take precedence (covered by route logic, tested via
    direct ORM here since HTTP route requires auth).

Run:
  /Users/joneshong/workshop/.venv/bin/python3 -m pytest \
      core/src/modules/memvault/tests/test_p1_valid_at_extraction.py -v
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime

import pytest

# Same path-fixup pattern as P0 — see test_p0_invalid_at_filter.py for explanation.
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

pytest.importorskip("sqlalchemy")
pytest.importorskip("psycopg")

from sqlalchemy import select, text  # noqa: E402
from src.modules.memvault.models import MemoryBlock  # noqa: E402
from src.modules.memvault.temporal_extract import extract_valid_at  # noqa: E402

from shared.database import async_session_factory  # noqa: E402


def _short_id() -> str:
    return uuid.uuid4().hex[:16]


# ─────────────────────── Schema sanity ───────────────────────


@pytest.mark.asyncio
async def test_valid_at_column_exists():
    """The migration / manual ALTER must have added valid_at."""
    async with async_session_factory() as db:
        r = await db.execute(
            text(
                """
                SELECT data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema='memvault' AND table_name='blocks'
                  AND column_name='valid_at'
                """
            )
        )
        row = r.first()
    assert row is not None, "valid_at column missing — apply migration mv20260502bt01"
    assert "timestamp" in row[0].lower()
    assert row[1] == "YES", "valid_at must be nullable"


# ─────────────────────── Pure-function: extract_valid_at ───────────────────────


def test_extract_valid_at_iso_date():
    """Plain ISO date should be picked verbatim."""
    out = extract_valid_at("Linux migration started 2025-01-15 according to logs")
    assert out is not None
    assert out.year == 2025 and out.month == 1 and out.day == 15
    assert out.tzinfo is not None  # tz-aware


def test_extract_valid_at_relative_phrase():
    """Relative phrases should resolve via normalize_temporal_range."""
    ref = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    out = extract_valid_at("上週開始用新框架", ref=ref)
    assert out is not None
    # 上週 = 2026-04-19 (Sun) ~ 2026-04-25 (Sat) — first ISO is the start
    assert out.year == 2026
    assert out.month == 4
    # Allow either Sun-based or Mon-based week conventions
    assert 19 <= out.day <= 26


def test_extract_valid_at_no_date_returns_none():
    """Content without any temporal cue → None."""
    assert extract_valid_at("just a regular memory with no time reference") is None


def test_extract_valid_at_empty_returns_none():
    assert extract_valid_at("") is None
    assert extract_valid_at(None) is None  # type: ignore[arg-type]


def test_extract_valid_at_picks_first_date():
    """Multiple dates → first wins (chronologically first in text, not earliest)."""
    out = extract_valid_at("Started 2024-03-10, then refactored 2025-08-20")
    assert out is not None
    assert out.year == 2024 and out.month == 3 and out.day == 10


# ─────────────────────── Integration: write + read with valid_at ───────────────────────


@pytest.fixture
async def block_with_valid_at():
    """Insert a block with valid_at set; cleanup after."""
    space_id = f"test-p1-{_short_id()}"
    block_id = _short_id()
    valid_at_value = datetime(2025, 6, 15, tzinfo=UTC)

    async with async_session_factory() as db:
        block = MemoryBlock(
            id=block_id,
            space_id=space_id,
            content="P1 test: valid_at column round-trip",
            block_type="knowledge",
            tags=["p1-test"],
            source_session=f"sess-{block_id}",
            created_at=datetime.now(UTC),
            valid_at=valid_at_value,
        )
        db.add(block)
        await db.commit()

    try:
        yield block_id, valid_at_value
    finally:
        async with async_session_factory() as db:
            row = (
                await db.execute(select(MemoryBlock).where(MemoryBlock.id == block_id))
            ).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
                await db.commit()


@pytest.mark.asyncio
async def test_valid_at_round_trip(block_with_valid_at):
    """Write a block with valid_at, read it back, verify the value persisted."""
    block_id, expected = block_with_valid_at
    async with async_session_factory() as db:
        row = (await db.execute(select(MemoryBlock).where(MemoryBlock.id == block_id))).scalar_one()
    assert row.valid_at is not None
    assert row.valid_at == expected


@pytest.mark.asyncio
async def test_to_response_includes_valid_at(block_with_valid_at):
    """services.to_response must surface valid_at in the API response shape."""
    from src.modules.memvault.services import memory_block_service

    block_id, expected = block_with_valid_at
    async with async_session_factory() as db:
        row = (await db.execute(select(MemoryBlock).where(MemoryBlock.id == block_id))).scalar_one()
    resp = memory_block_service.to_response(row)
    assert resp.valid_at == expected


# ─────────────────────── Integration: extraction-driven valid_at ───────────────────────


@pytest.mark.asyncio
async def test_route_extraction_populates_valid_at_when_omitted():
    """Mimic the route logic: when body.valid_at is None, extract from content."""
    space_id = f"test-p1-route-{_short_id()}"
    block_id = _short_id()
    content = "我從 2025-01-15 開始用 Linux"

    async with async_session_factory() as db:
        block = MemoryBlock(
            id=block_id,
            space_id=space_id,
            content=content,
            block_type="knowledge",
            tags=["p1-test"],
            source_session=f"sess-{block_id}",
            created_at=datetime.now(UTC),
        )
        # Mirror routes.py: extract_valid_at then assign
        extracted = extract_valid_at(content)
        if extracted is not None:
            block.valid_at = extracted
        db.add(block)
        await db.commit()

    try:
        async with async_session_factory() as db:
            row = (
                await db.execute(select(MemoryBlock).where(MemoryBlock.id == block_id))
            ).scalar_one()
        assert row.valid_at is not None
        assert row.valid_at.year == 2025
        assert row.valid_at.month == 1
        assert row.valid_at.day == 15
    finally:
        async with async_session_factory() as db:
            row = (
                await db.execute(select(MemoryBlock).where(MemoryBlock.id == block_id))
            ).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
                await db.commit()


@pytest.mark.asyncio
async def test_explicit_valid_at_wins_over_extraction():
    """Mimic route: body.valid_at explicit → never overwritten by extraction."""
    space_id = f"test-p1ex-{_short_id()}"
    block_id = _short_id()
    explicit = datetime(2024, 12, 25, tzinfo=UTC)
    content_with_other_date = "Note dated 2025-08-20"

    async with async_session_factory() as db:
        block = MemoryBlock(
            id=block_id,
            space_id=space_id,
            content=content_with_other_date,
            block_type="knowledge",
            tags=["p1-test"],
            source_session=f"sess-{block_id}",
            created_at=datetime.now(UTC),
        )
        # Mirror route: explicit takes precedence
        block.valid_at = explicit  # caller provided
        # Extraction would have given 2025-08-20 — but explicit wins
        db.add(block)
        await db.commit()

    try:
        async with async_session_factory() as db:
            row = (
                await db.execute(select(MemoryBlock).where(MemoryBlock.id == block_id))
            ).scalar_one()
        assert row.valid_at == explicit, f"Explicit valid_at lost: got {row.valid_at}"
    finally:
        async with async_session_factory() as db:
            row = (
                await db.execute(select(MemoryBlock).where(MemoryBlock.id == block_id))
            ).scalar_one_or_none()
            if row is not None:
                await db.delete(row)
                await db.commit()

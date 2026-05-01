"""P2 integration test — bitemporal as_of (time-travel) recall.

Real PG required. Setup: 3 blocks across time, with super-session/invalidation chain.
Verifies that text_search and the recent-fallback path behave correctly under:

  Block A: valid_at=2026-01-01, invalid_at=2026-03-01 (lived Jan~Feb)
  Block B: valid_at=2026-02-15, invalid_at=NULL       (still alive, started in Feb)
  Block C: valid_at=2026-04-01, invalid_at=NULL       (still alive, started in Apr)

Expected as_of results (with the same content keyword):
  as_of=None        → {B, C}                  (current view: A is invalid)
  as_of=2026-01-15  → {A}                     (only A had started; B not yet, C not yet)
  as_of=2026-02-20  → {A, B}                  (A still valid, B started, C not yet)
  as_of=2026-03-15  → {B}                     (A invalid, B still valid, C not yet)
  as_of=2026-04-15  → {B, C}                  (A invalid, B/C valid)

Run:
  /Users/joneshong/workshop/.venv/bin/python3 -m pytest \
      core/src/modules/memvault/tests/test_p2_as_of_recall.py -v
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime

import pytest

# Path fixup — see test_p0_invalid_at_filter.py for explanation.
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

from sqlalchemy import func, or_, select  # noqa: E402
from src.modules.memvault.models import MemoryBlock  # noqa: E402
from src.modules.memvault.services import memory_block_service  # noqa: E402

from shared.database import async_session_factory  # noqa: E402

KEYWORD = "p2asofbeacon"


def _short_id() -> str:
    return uuid.uuid4().hex[:16]


@pytest.fixture
async def three_blocks_across_time():
    """Insert A (Jan, dead in Mar), B (Feb, alive), C (Apr, alive)."""
    space_id = f"test-p2-{_short_id()}"
    a_id, b_id, c_id = _short_id(), _short_id(), _short_id()

    async with async_session_factory() as db:
        a = MemoryBlock(
            id=a_id,
            space_id=space_id,
            content=f"A: {KEYWORD} block valid Jan~Feb",
            block_type="knowledge",
            tags=["p2-test"],
            source_session=f"sess-a-{a_id}",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            valid_at=datetime(2026, 1, 1, tzinfo=UTC),
            invalid_at=datetime(2026, 3, 1, tzinfo=UTC),
            superseded_by=b_id,
        )
        b = MemoryBlock(
            id=b_id,
            space_id=space_id,
            content=f"B: {KEYWORD} block alive since Feb",
            block_type="knowledge",
            tags=["p2-test"],
            source_session=f"sess-b-{b_id}",
            created_at=datetime(2026, 2, 15, tzinfo=UTC),
            valid_at=datetime(2026, 2, 15, tzinfo=UTC),
        )
        c = MemoryBlock(
            id=c_id,
            space_id=space_id,
            content=f"C: {KEYWORD} block alive since Apr",
            block_type="knowledge",
            tags=["p2-test"],
            source_session=f"sess-c-{c_id}",
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
            valid_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
        db.add_all([a, b, c])
        await db.commit()

    try:
        yield space_id, a_id, b_id, c_id
    finally:
        # Delete A first (FK references B via superseded_by), then B and C.
        async with async_session_factory() as db:
            for bid in (a_id, b_id, c_id):
                row = (
                    await db.execute(select(MemoryBlock).where(MemoryBlock.id == bid))
                ).scalar_one_or_none()
                if row is not None:
                    await db.delete(row)
                    await db.commit()


def _ids_from_results(results) -> set[str]:
    """SemanticSearchResult or MemoryBlockResponse → {block.id}."""
    return {(r.block.id if hasattr(r, "block") else r.id) for r in results}


# ─────────────────────── as_of=None: current view ───────────────────────


@pytest.mark.asyncio
async def test_text_search_current_view(three_blocks_across_time):
    """as_of=None → only currently-valid blocks (B + C); A is invalid."""
    space_id, a_id, b_id, c_id = three_blocks_across_time
    async with async_session_factory() as db:
        results = await memory_block_service.text_search(
            db, space_id=space_id, query=KEYWORD, top_k=10
        )
    ids = _ids_from_results(results)
    assert a_id not in ids, "Invalid block A must not appear in current view"
    assert b_id in ids
    assert c_id in ids


# ─────────────────────── as_of=T: time travel ───────────────────────


@pytest.mark.asyncio
async def test_text_search_as_of_jan_only_a(three_blocks_across_time):
    """as_of=2026-01-15: only A had started (B starts Feb-15, C starts Apr-1)."""
    space_id, a_id, _b_id, _c_id = three_blocks_across_time
    as_of = datetime(2026, 1, 15, tzinfo=UTC)
    async with async_session_factory() as db:
        results = await memory_block_service.text_search(
            db, space_id=space_id, query=KEYWORD, top_k=10, as_of=as_of
        )
    ids = _ids_from_results(results)
    assert ids == {a_id}, f"Expected only A; got {ids}"


@pytest.mark.asyncio
async def test_text_search_as_of_feb_a_and_b(three_blocks_across_time):
    """as_of=2026-02-20: A still valid (invalid_at=Mar-1), B started; C not yet."""
    space_id, a_id, b_id, _c_id = three_blocks_across_time
    as_of = datetime(2026, 2, 20, tzinfo=UTC)
    async with async_session_factory() as db:
        results = await memory_block_service.text_search(
            db, space_id=space_id, query=KEYWORD, top_k=10, as_of=as_of
        )
    ids = _ids_from_results(results)
    assert ids == {a_id, b_id}, f"Expected A+B; got {ids}"


@pytest.mark.asyncio
async def test_text_search_as_of_mar_only_b(three_blocks_across_time):
    """as_of=2026-03-15: A invalid (Mar-1), B alive, C not yet."""
    space_id, _a_id, b_id, _c_id = three_blocks_across_time
    as_of = datetime(2026, 3, 15, tzinfo=UTC)
    async with async_session_factory() as db:
        results = await memory_block_service.text_search(
            db, space_id=space_id, query=KEYWORD, top_k=10, as_of=as_of
        )
    ids = _ids_from_results(results)
    assert ids == {b_id}, f"Expected only B; got {ids}"


@pytest.mark.asyncio
async def test_text_search_as_of_apr_b_and_c(three_blocks_across_time):
    """as_of=2026-04-15: A invalid, B alive, C alive."""
    space_id, _a_id, b_id, c_id = three_blocks_across_time
    as_of = datetime(2026, 4, 15, tzinfo=UTC)
    async with async_session_factory() as db:
        results = await memory_block_service.text_search(
            db, space_id=space_id, query=KEYWORD, top_k=10, as_of=as_of
        )
    ids = _ids_from_results(results)
    assert ids == {b_id, c_id}, f"Expected B+C; got {ids}"


# ─────────────────────── Edge cases ───────────────────────


@pytest.mark.asyncio
async def test_recent_fallback_query_runtime_pattern(three_blocks_across_time):
    """Recent-fallback path (query_runtime.py:321-329) under as_of=2026-02-20 → A+B."""
    space_id, a_id, b_id, _c_id = three_blocks_across_time
    as_of = datetime(2026, 2, 20, tzinfo=UTC)
    # Mirror exactly what query_runtime now does
    temporal_filters = [
        MemoryBlock.deleted_at.is_(None),
        func.coalesce(MemoryBlock.valid_at, MemoryBlock.created_at) <= as_of,
        or_(MemoryBlock.invalid_at.is_(None), MemoryBlock.invalid_at > as_of),
    ]
    async with async_session_factory() as db:
        q = (
            select(MemoryBlock)
            .where(MemoryBlock.space_id == space_id, *temporal_filters)
            .order_by(MemoryBlock.created_at.desc())
            .limit(10)
        )
        rows = (await db.execute(q)).scalars().all()
    ids = {r.id for r in rows}
    assert ids == {a_id, b_id}, f"Recent fallback as_of=2026-02-20 expected A+B; got {ids}"


@pytest.mark.asyncio
async def test_as_of_at_invalidation_boundary_excludes(three_blocks_across_time):
    """as_of EQUAL to A.invalid_at (2026-03-01) — must EXCLUDE A.

    Filter: invalid_at > as_of. A.invalid_at == 2026-03-01 → 03-01 > 03-01 is FALSE → A excluded.
    This is the inclusive/exclusive boundary contract — invalid_at is when fact
    STOPPED being true, so 'as of T' where T == invalid_at means fact already gone.
    """
    space_id, a_id, b_id, _c_id = three_blocks_across_time
    as_of = datetime(2026, 3, 1, tzinfo=UTC)
    async with async_session_factory() as db:
        results = await memory_block_service.text_search(
            db, space_id=space_id, query=KEYWORD, top_k=10, as_of=as_of
        )
    ids = _ids_from_results(results)
    assert a_id not in ids, "A.invalid_at == as_of → must be excluded"
    assert b_id in ids


@pytest.mark.asyncio
async def test_as_of_before_any_block(three_blocks_across_time):
    """as_of way before all blocks → empty result (nothing was valid yet)."""
    space_id, _a_id, _b_id, _c_id = three_blocks_across_time
    as_of = datetime(2025, 1, 1, tzinfo=UTC)
    async with async_session_factory() as db:
        results = await memory_block_service.text_search(
            db, space_id=space_id, query=KEYWORD, top_k=10, as_of=as_of
        )
    ids = _ids_from_results(results)
    assert ids == set(), f"as_of before all blocks must be empty; got {ids}"

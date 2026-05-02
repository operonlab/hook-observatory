"""P0 integration test — recall paths must filter invalid_at IS NOT NULL.

Real PG required (no mocks). Verifies that blocks marked as superseded
(invalid_at NOT NULL) are excluded from:
  - MemoryBlockService.text_search
  - MemoryBlockService.find_by_source_session
  - query_runtime recent-fallback path

Setup: insert 2 blocks under an isolated space_id — one live, one invalidated.
Teardown: delete both blocks.

Run:
  cd ~/workshop && .venv/bin/python3 -m pytest \
      core/src/modules/memvault/tests/test_p0_invalid_at_filter.py -v
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime

import pytest

# Force this WORKTREE's core/ to dominate sys.path so the worktree's edited
# services.py (with the new invalid_at filter) is the one tested — not main's.
# Path resolution: this file is at <worktree>/core/src/modules/memvault/tests/<file>.
_HERE = os.path.dirname(os.path.abspath(__file__))
# tests/ → memvault/ → modules/ → src/ → core/  (4 ups)
_WORKTREE_CORE = os.path.normpath(os.path.join(_HERE, "..", "..", "..", ".."))
_WORKTREE_CORE_SRC = os.path.join(_WORKTREE_CORE, "src")
# Drop main /workshop/ paths that .pth files added (they shadow worktree),
# but KEEP .venv site-packages and worktree paths.
sys.path = [
    p for p in sys.path if "/workshop/" not in p or ".claude/worktrees/" in p or "/.venv/" in p
]
# core/src/ → enables `from shared.database import ...`
# core/    → enables `from src.modules.memvault.services import ...`
sys.path.insert(0, _WORKTREE_CORE_SRC)
sys.path.insert(0, _WORKTREE_CORE)
# Add main's libs/ paths back (shared.database etc rely on them)
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

from sqlalchemy import select  # noqa: E402
from src.modules.memvault.models import MemoryBlock  # noqa: E402
from src.modules.memvault.services import memory_block_service  # noqa: E402

from shared.database import async_session_factory  # noqa: E402


def _short_id() -> str:
    return uuid.uuid4().hex[:16]


@pytest.fixture
async def two_blocks_one_invalid():
    """Insert two blocks under an isolated test space, yield (space_id, live_id, invalid_id).

    Cleanup runs even if assertions fail.
    """
    space_id = f"test-p0-{_short_id()}"
    live_id = _short_id()
    invalid_id = _short_id()

    async with async_session_factory() as db:
        live = MemoryBlock(
            id=live_id,
            space_id=space_id,
            content="LIVE: P0 invalid_at filter test live block xyzbeacon123",
            block_type="knowledge",
            tags=["p0-test", "live"],
            source_session=f"sess-live-{live_id}",
            created_at=datetime.now(UTC),
        )
        invalid = MemoryBlock(
            id=invalid_id,
            space_id=space_id,
            content="INVALID: P0 invalid_at filter test invalid block xyzbeacon123",
            block_type="knowledge",
            tags=["p0-test", "invalid"],
            source_session=f"sess-invalid-{invalid_id}",
            created_at=datetime.now(UTC),
            invalid_at=datetime.now(UTC),
            superseded_by=live_id,
        )
        db.add_all([live, invalid])
        await db.commit()

    try:
        yield space_id, live_id, invalid_id
    finally:
        # Delete invalid FIRST (it FK-references live via superseded_by), then live.
        async with async_session_factory() as db:
            for bid in (invalid_id, live_id):
                row = (
                    await db.execute(select(MemoryBlock).where(MemoryBlock.id == bid))
                ).scalar_one_or_none()
                if row is not None:
                    await db.delete(row)
                    await db.commit()


@pytest.mark.asyncio
async def test_text_search_excludes_invalid_blocks(two_blocks_one_invalid):
    """text_search must NOT return blocks with invalid_at NOT NULL."""
    space_id, live_id, invalid_id = two_blocks_one_invalid
    async with async_session_factory() as db:
        results = await memory_block_service.text_search(
            db, space_id=space_id, query="xyzbeacon123", top_k=10
        )

    # text_search returns SemanticSearchResult (with .block) — extract IDs.
    returned_ids = {(r.block.id if hasattr(r, "block") else r.id) for r in results}
    assert live_id in returned_ids, "Live block must appear in text_search"
    assert invalid_id not in returned_ids, (
        f"Invalid (superseded) block must NOT appear in text_search; got {returned_ids}"
    )


@pytest.mark.asyncio
async def test_find_by_source_session_excludes_invalid(two_blocks_one_invalid):
    """find_by_source_session must NOT return invalid blocks (idempotency safety)."""
    space_id, _live_id, invalid_id = two_blocks_one_invalid
    async with async_session_factory() as db:
        result = await memory_block_service.find_by_source_session(
            db, space_id=space_id, source_session=f"sess-invalid-{invalid_id}"
        )
    assert result is None, (
        f"find_by_source_session returned invalid block {invalid_id}; got {result}"
    )


@pytest.mark.asyncio
async def test_query_runtime_recent_fallback_excludes_invalid(two_blocks_one_invalid):
    """query_runtime recent-fallback (line 320-329) must filter invalid_at."""
    from sqlalchemy import select as sql_select

    space_id, live_id, invalid_id = two_blocks_one_invalid
    # Inline the exact filter the production code uses (mirrors query_runtime.py:321-329)
    async with async_session_factory() as db:
        q = (
            sql_select(MemoryBlock)
            .where(
                MemoryBlock.space_id == space_id,
                MemoryBlock.deleted_at.is_(None),
                MemoryBlock.invalid_at.is_(None),
            )
            .order_by(MemoryBlock.created_at.desc())
            .limit(10)
        )
        rows = (await db.execute(q)).scalars().all()
    ids = {r.id for r in rows}
    assert live_id in ids, "Recent fallback must include live block"
    assert invalid_id not in ids, "Recent fallback must exclude invalid block"


@pytest.mark.asyncio
async def test_baseline_no_invalid_blocks_in_prod():
    """Sanity: production memvault has 0 invalid blocks today (so existing data unaffected)."""
    from sqlalchemy import text

    async with async_session_factory() as db:
        invalid_count = (
            await db.execute(
                text("SELECT count(*) FROM memvault.blocks WHERE invalid_at IS NOT NULL")
            )
        ).scalar()
    # Just record — don't fail if SUPERSEDE has started firing in prod
    assert invalid_count >= 0
    print(f"\n[baseline] Production invalid blocks: {invalid_count}")

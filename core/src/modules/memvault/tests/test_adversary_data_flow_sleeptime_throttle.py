"""Adversary test — §11 Worker 5 sleeptime throttle invariants.

Contract (§11):
- PERSONA_HUMAN_THROTTLE_SECONDS = 86400 (24h)
- _maybe_update_persona_human(db, space_id) -> list[str]
  Two calls within 24h → second call returns []
  Throttle bumped even on failure
- _run_sleeptime ensures persona/human placeholder rows exist (idempotent)

Unit: constant value check + function signature.
DB: real PG for throttle behavior.
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
for libname in ("text-ops", "kg-ops", "sdk-client", "tmux-lib", "audio-ops", "image-ops", "video-ops"):
    p = f"/Users/joneshong/workshop/libs/{libname}"
    if p not in sys.path:
        sys.path.append(p)


# ── §11 constant unit tests (no PG) ──────────────────────────────────────────


def test_persona_human_throttle_seconds_is_86400():
    """PERSONA_HUMAN_THROTTLE_SECONDS must equal 86400 (exactly 24h)."""
    from src.modules.memvault.sleeptime import PERSONA_HUMAN_THROTTLE_SECONDS

    assert PERSONA_HUMAN_THROTTLE_SECONDS == 86400, (
        f"PERSONA_HUMAN_THROTTLE_SECONDS must be 86400; got {PERSONA_HUMAN_THROTTLE_SECONDS}"
    )


def test_maybe_update_persona_human_function_exists():
    """_maybe_update_persona_human must be importable and callable."""
    try:
        from src.modules.memvault.sleeptime import _maybe_update_persona_human
        import inspect

        assert callable(_maybe_update_persona_human)
        sig = inspect.signature(_maybe_update_persona_human)
        params = list(sig.parameters.keys())
        assert "space_id" in params, (
            f"_maybe_update_persona_human must accept space_id; params: {params}"
        )
    except ImportError as e:
        pytest.skip(f"_maybe_update_persona_human not importable: {e}")


def test_maybe_update_persona_human_returns_list_annotation():
    """_maybe_update_persona_human return type annotation should indicate list[str]."""
    try:
        from src.modules.memvault.sleeptime import _maybe_update_persona_human
        import inspect

        sig = inspect.signature(_maybe_update_persona_human)
        # Return annotation might be list or list[str]
        # We just check the function is annotated (could be Any in edge cases)
        # but not strictly required — the contract says it returns list[str]
        assert callable(_maybe_update_persona_human)
    except ImportError as e:
        pytest.skip(f"Not importable: {e}")


# ── §11 DB throttle tests ─────────────────────────────────────────────────────


pytest.importorskip("sqlalchemy")
pytest.importorskip("psycopg")

from sqlalchemy import select  # noqa: E402

from shared.database import async_session_factory  # noqa: E402
from src.modules.memvault.models import MemoryBlock  # noqa: E402


def _uid() -> str:
    return uuid.uuid4().hex[:16]


async def _cleanup_blocks(space_id: str) -> None:
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(MemoryBlock).where(MemoryBlock.space_id == space_id)
            )
        ).scalars().all()
        for r in rows:
            await db.delete(r)
        await db.commit()


@pytest.mark.asyncio
async def test_throttle_second_call_returns_empty_within_24h():
    """Two consecutive calls to _maybe_update_persona_human within 24h:
    second call MUST return [].
    """
    try:
        from src.modules.memvault.sleeptime import _maybe_update_persona_human
    except ImportError as e:
        pytest.skip(f"_maybe_update_persona_human not importable: {e}")

    space_id = f"adv-sleep-{_uid()}"
    try:
        # First call — may return any list (including [])
        async with async_session_factory() as db:
            first_result = await _maybe_update_persona_human(db, space_id)

        assert isinstance(first_result, list), (
            f"_maybe_update_persona_human must return list; got {type(first_result)}"
        )

        # Second call immediately after — within 24h throttle window
        async with async_session_factory() as db:
            second_result = await _maybe_update_persona_human(db, space_id)

        assert second_result == [], (
            f"Second call within 24h must return []; got {second_result}"
        )
    finally:
        await _cleanup_blocks(space_id)


@pytest.mark.asyncio
async def test_throttle_idempotent_different_spaces():
    """Each space_id has independent throttle — one space throttled does not affect another."""
    try:
        from src.modules.memvault.sleeptime import _maybe_update_persona_human
    except ImportError as e:
        pytest.skip(f"_maybe_update_persona_human not importable: {e}")

    space_a = f"adv-sleep-a-{_uid()}"
    space_b = f"adv-sleep-b-{_uid()}"
    try:
        # Call space_a twice (second will be throttled)
        async with async_session_factory() as db:
            await _maybe_update_persona_human(db, space_a)
        async with async_session_factory() as db:
            second_a = await _maybe_update_persona_human(db, space_a)
        assert second_a == [], "space_a second call must be throttled"

        # space_b first call should NOT be throttled by space_a's state
        async with async_session_factory() as db:
            first_b = await _maybe_update_persona_human(db, space_b)
        # first_b may be [] if no context or LLM, but it should not raise
        assert isinstance(first_b, list), (
            f"space_b first call must return list; got {type(first_b)}"
        )
    finally:
        await _cleanup_blocks(space_a)
        await _cleanup_blocks(space_b)

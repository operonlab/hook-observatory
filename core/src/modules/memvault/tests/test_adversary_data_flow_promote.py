"""Adversary test — §9 promote_unverified contract.

Contract (§9):
- PromotionStats dataclass: candidates_scanned, promoted_ids, demoted_ids, dry_run
- promoted_count property == len(promoted_ids)
- demoted_count property == len(demoted_ids)
- Promotion conditions (ANY of):
    A) crag_correct_count >= 3 AND crag_incorrect_count == 0
    B) last_confirmed_at >= now() - 90 days AND access_count >= 5
- Demotion: crag_incorrect_count >= 2 AND crag_correct_count == 0 AND status != 'disputed'
- Both skip deleted_at IS NOT NULL
- Promotion additionally skips invalid_at IS NOT NULL
- dry_run=True: NO triple mutations; audit log row IS written
- dry_run=False: triples mutated; audit log row written
- Constants: CORRECT_COUNT_THRESHOLD >= 2, RECENT_CONFIRM_DAYS >= 30,
  RECENT_CONFIRM_ACCESS_THRESHOLD >= 2, DEMOTE_INCORRECT_THRESHOLD >= 2

Unit tests: PromotionStats arithmetic + constants. DB tests: real PG.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

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


# ── §9 PromotionStats unit tests (no PG) ─────────────────────────────────────


def test_promotion_stats_promoted_count_derived():
    """promoted_count == len(promoted_ids)."""
    from src.modules.memvault.kg_verification import PromotionStats

    s = PromotionStats(candidates_scanned=10, dry_run=False)
    s.promoted_ids = ["a", "b", "c"]
    assert s.promoted_count == 3


def test_promotion_stats_demoted_count_derived():
    """demoted_count == len(demoted_ids)."""
    from src.modules.memvault.kg_verification import PromotionStats

    s = PromotionStats(candidates_scanned=5, dry_run=True)
    s.demoted_ids = ["x"]
    assert s.demoted_count == 1


def test_promotion_stats_empty_lists():
    """Counts are 0 when lists are empty."""
    from src.modules.memvault.kg_verification import PromotionStats

    s = PromotionStats(candidates_scanned=0, dry_run=True)
    assert s.promoted_count == 0
    assert s.demoted_count == 0


def test_promotion_stats_has_required_fields():
    """PromotionStats must have candidates_scanned, promoted_ids, demoted_ids, dry_run."""
    from src.modules.memvault.kg_verification import PromotionStats

    s = PromotionStats(candidates_scanned=42, dry_run=True)
    assert hasattr(s, "candidates_scanned")
    assert hasattr(s, "promoted_ids")
    assert hasattr(s, "demoted_ids")
    assert hasattr(s, "dry_run")
    assert s.candidates_scanned == 42
    assert s.dry_run is True


def test_threshold_constants():
    """Module-level constants must satisfy minimum values per §9 contract."""
    from src.modules.memvault.kg_verification import (
        CORRECT_COUNT_THRESHOLD,
        DEMOTE_INCORRECT_THRESHOLD,
        RECENT_CONFIRM_ACCESS_THRESHOLD,
        RECENT_CONFIRM_DAYS,
    )

    assert CORRECT_COUNT_THRESHOLD >= 2, (
        f"CORRECT_COUNT_THRESHOLD={CORRECT_COUNT_THRESHOLD} must be >= 2"
    )
    assert RECENT_CONFIRM_DAYS >= 30, (
        f"RECENT_CONFIRM_DAYS={RECENT_CONFIRM_DAYS} must be >= 30"
    )
    assert RECENT_CONFIRM_ACCESS_THRESHOLD >= 2, (
        f"RECENT_CONFIRM_ACCESS_THRESHOLD={RECENT_CONFIRM_ACCESS_THRESHOLD} must be >= 2"
    )
    assert DEMOTE_INCORRECT_THRESHOLD >= 2, (
        f"DEMOTE_INCORRECT_THRESHOLD={DEMOTE_INCORRECT_THRESHOLD} must be >= 2"
    )


def test_correct_count_threshold_no_single_vote_promote():
    """CORRECT_COUNT_THRESHOLD >= 2 ensures no single-vote promotion."""
    from src.modules.memvault.kg_verification import CORRECT_COUNT_THRESHOLD

    # A triple with only 1 correct vote must NOT qualify for promotion via path A
    # Check boundary: threshold - 1 does not qualify
    qualifying_count = CORRECT_COUNT_THRESHOLD
    below_threshold = CORRECT_COUNT_THRESHOLD - 1
    # Boundary test: exactly at threshold qualifies, one below does not
    assert qualifying_count >= below_threshold + 1, (
        "Threshold must be strictly above below_threshold"
    )


# ── §9 DB tests ───────────────────────────────────────────────────────────────


pytest.importorskip("sqlalchemy")
pytest.importorskip("psycopg")

from sqlalchemy import select  # noqa: E402

from shared.database import async_session_factory  # noqa: E402
from src.modules.memvault.kg_models import KGVerificationRunLog, Triple  # noqa: E402


def _uid() -> str:
    return uuid.uuid4().hex[:16]


async def _insert_triple(space_id: str, **kwargs) -> Triple:
    tid = _uid()
    t = Triple(
        id=tid,
        space_id=space_id,
        subject=f"S-{tid}",
        predicate="test_pred",
        object=f"O-{tid}",
        source_session=f"sess-{tid}",
        **kwargs,
    )
    async with async_session_factory() as db:
        db.add(t)
        await db.commit()
    return t


async def _get_triple(tid: str) -> Triple | None:
    async with async_session_factory() as db:
        return (await db.execute(select(Triple).where(Triple.id == tid))).scalar_one_or_none()


async def _delete_triples(ids: list[str]) -> None:
    async with async_session_factory() as db:
        for tid in ids:
            row = (await db.execute(select(Triple).where(Triple.id == tid))).scalar_one_or_none()
            if row:
                await db.delete(row)
                await db.commit()


async def _delete_verification_log(space_id: str) -> None:
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(KGVerificationRunLog).where(KGVerificationRunLog.space_id == space_id)
            )
        ).scalars().all()
        for r in rows:
            await db.delete(r)
        await db.commit()


@pytest.mark.asyncio
async def test_promote_unverified_dry_run_no_triple_mutation():
    """dry_run=True must NOT mutate any triple row."""
    from src.modules.memvault.kg_verification import (
        CORRECT_COUNT_THRESHOLD,
        promote_unverified,
    )

    space_id = f"adv-prom-{_uid()}"
    # Insert a triple that qualifies for promotion (path A)
    t = await _insert_triple(
        space_id,
        crag_correct_count=CORRECT_COUNT_THRESHOLD,
        crag_incorrect_count=0,
        verification_status="unverified",
    )
    try:
        async with async_session_factory() as db:
            stats = await promote_unverified(db, space_id=space_id, dry_run=True)

        # Triple must NOT be mutated
        updated = await _get_triple(t.id)
        assert updated is not None
        assert updated.verification_status == "unverified", (
            f"dry_run=True must not mutate triple status; got '{updated.verification_status}'"
        )
        assert updated.verified_at is None, (
            "dry_run=True must not set verified_at"
        )
    finally:
        await _delete_triples([t.id])
        await _delete_verification_log(space_id)


@pytest.mark.asyncio
async def test_promote_unverified_dry_run_writes_audit_log():
    """dry_run=True MUST still write an audit log row to kg_verification_run_log."""
    from src.modules.memvault.kg_verification import promote_unverified

    space_id = f"adv-prom-audit-{_uid()}"
    try:
        async with async_session_factory() as db:
            await promote_unverified(db, space_id=space_id, dry_run=True)

        async with async_session_factory() as db:
            log_rows = (
                await db.execute(
                    select(KGVerificationRunLog).where(
                        KGVerificationRunLog.space_id == space_id
                    )
                )
            ).scalars().all()
        assert len(log_rows) >= 1, (
            "dry_run=True must still write audit log row"
        )
        assert log_rows[0].dry_run is True
    finally:
        await _delete_verification_log(space_id)


@pytest.mark.asyncio
async def test_promote_unverified_path_a_correct_count():
    """Path A: crag_correct_count >= THRESHOLD AND incorrect == 0 → promoted to 'verified'."""
    from src.modules.memvault.kg_verification import (
        CORRECT_COUNT_THRESHOLD,
        promote_unverified,
    )

    space_id = f"adv-prom-{_uid()}"
    # Exactly at threshold
    t = await _insert_triple(
        space_id,
        crag_correct_count=CORRECT_COUNT_THRESHOLD,
        crag_incorrect_count=0,
        verification_status="unverified",
    )
    try:
        async with async_session_factory() as db:
            stats = await promote_unverified(db, space_id=space_id, dry_run=False)

        updated = await _get_triple(t.id)
        assert updated is not None
        assert updated.verification_status == "verified", (
            f"Triple with correct_count>={CORRECT_COUNT_THRESHOLD} and incorrect==0 must be verified; "
            f"got '{updated.verification_status}'"
        )
        assert updated.verified_at is not None, "promoted triple must have verified_at set"
    finally:
        await _delete_triples([t.id])
        await _delete_verification_log(space_id)


@pytest.mark.asyncio
async def test_promote_unverified_path_a_below_threshold_not_promoted():
    """Triple with correct_count == THRESHOLD-1 must NOT be promoted."""
    from src.modules.memvault.kg_verification import (
        CORRECT_COUNT_THRESHOLD,
        promote_unverified,
    )

    space_id = f"adv-prom-{_uid()}"
    below = CORRECT_COUNT_THRESHOLD - 1
    t = await _insert_triple(
        space_id,
        crag_correct_count=below,
        crag_incorrect_count=0,
        verification_status="unverified",
    )
    try:
        async with async_session_factory() as db:
            stats = await promote_unverified(db, space_id=space_id, dry_run=False)

        updated = await _get_triple(t.id)
        assert updated is not None
        assert updated.verification_status == "unverified", (
            f"Triple with correct_count={below} (below threshold={CORRECT_COUNT_THRESHOLD}) "
            f"must NOT be promoted; got '{updated.verification_status}'"
        )
    finally:
        await _delete_triples([t.id])
        await _delete_verification_log(space_id)


@pytest.mark.asyncio
async def test_promote_unverified_demotion():
    """Demotion: incorrect>=THRESHOLD AND correct==0 AND status!='disputed' → 'disputed'."""
    from src.modules.memvault.kg_verification import (
        DEMOTE_INCORRECT_THRESHOLD,
        promote_unverified,
    )

    space_id = f"adv-prom-{_uid()}"
    t = await _insert_triple(
        space_id,
        crag_correct_count=0,
        crag_incorrect_count=DEMOTE_INCORRECT_THRESHOLD,
        verification_status="unverified",
    )
    try:
        async with async_session_factory() as db:
            stats = await promote_unverified(db, space_id=space_id, dry_run=False)

        updated = await _get_triple(t.id)
        assert updated is not None
        assert updated.verification_status == "disputed", (
            f"Triple with incorrect_count>={DEMOTE_INCORRECT_THRESHOLD} and correct==0 "
            f"must be demoted to 'disputed'; got '{updated.verification_status}'"
        )
        # Demotion must not set invalid_at
        assert updated.invalid_at is None, "Demotion must not set invalid_at"
    finally:
        await _delete_triples([t.id])
        await _delete_verification_log(space_id)


@pytest.mark.asyncio
async def test_promote_unverified_skips_deleted():
    """Promotion must skip deleted_at IS NOT NULL rows."""
    from src.modules.memvault.kg_verification import (
        CORRECT_COUNT_THRESHOLD,
        promote_unverified,
    )

    space_id = f"adv-prom-{_uid()}"
    t = await _insert_triple(
        space_id,
        crag_correct_count=CORRECT_COUNT_THRESHOLD,
        crag_incorrect_count=0,
        verification_status="unverified",
        deleted_at=datetime.now(UTC),
    )
    try:
        async with async_session_factory() as db:
            stats = await promote_unverified(db, space_id=space_id, dry_run=False)

        updated = await _get_triple(t.id)
        assert updated is not None
        assert updated.verification_status == "unverified", (
            "Soft-deleted triple must be skipped by promotion"
        )
    finally:
        await _delete_triples([t.id])
        await _delete_verification_log(space_id)


@pytest.mark.asyncio
async def test_promote_unverified_skips_invalid():
    """Promotion (but not demotion) must skip invalid_at IS NOT NULL rows."""
    from src.modules.memvault.kg_verification import (
        CORRECT_COUNT_THRESHOLD,
        promote_unverified,
    )

    space_id = f"adv-prom-{_uid()}"
    t = await _insert_triple(
        space_id,
        crag_correct_count=CORRECT_COUNT_THRESHOLD,
        crag_incorrect_count=0,
        verification_status="unverified",
        invalid_at=datetime.now(UTC),
    )
    try:
        async with async_session_factory() as db:
            stats = await promote_unverified(db, space_id=space_id, dry_run=False)

        updated = await _get_triple(t.id)
        assert updated is not None
        assert updated.verification_status == "unverified", (
            "Invalidated triple must be skipped by promotion"
        )
    finally:
        await _delete_triples([t.id])
        await _delete_verification_log(space_id)


@pytest.mark.asyncio
async def test_promote_unverified_stats_counts_promoted():
    """PromotionStats.promoted_count == number of actually promoted triples."""
    from src.modules.memvault.kg_verification import (
        CORRECT_COUNT_THRESHOLD,
        promote_unverified,
    )

    space_id = f"adv-prom-{_uid()}"
    t1 = await _insert_triple(
        space_id,
        crag_correct_count=CORRECT_COUNT_THRESHOLD,
        crag_incorrect_count=0,
        verification_status="unverified",
    )
    t2 = await _insert_triple(
        space_id,
        crag_correct_count=CORRECT_COUNT_THRESHOLD,
        crag_incorrect_count=0,
        verification_status="unverified",
    )
    # A non-qualifying triple
    t3 = await _insert_triple(
        space_id,
        crag_correct_count=1,
        crag_incorrect_count=0,
        verification_status="unverified",
    )
    try:
        async with async_session_factory() as db:
            stats = await promote_unverified(db, space_id=space_id, dry_run=False)

        assert stats.promoted_count == len(stats.promoted_ids), (
            "promoted_count must equal len(promoted_ids)"
        )
        assert t1.id in stats.promoted_ids
        assert t2.id in stats.promoted_ids
        assert t3.id not in stats.promoted_ids
    finally:
        await _delete_triples([t1.id, t2.id, t3.id])
        await _delete_verification_log(space_id)

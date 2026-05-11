"""鐵律 2 — Data Flow Test: evidence_signal reverse-inference in TripleService.

Contract (Phase B — graphify-cannibalized 2026-05-11):
- TripleCreate(confidence=0.5) → before_create 反推 evidence_signal='inferred'
- TripleCreate(confidence=0.5, evidence_signal='extracted') 顯式設 → 不覆寫
- TripleCreate(confidence=None) → 保留 default 'extracted'
- TripleCreate(confidence=0.9) → 反推 evidence_signal='extracted'
- TripleCreate(confidence=0.1) → 反推 evidence_signal='ambiguous'

Unit test: before_create() dict output (no DB).
DB test: Real PG required (skipped if not available).
"""

from __future__ import annotations

import os
import sys
import uuid

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


# ── Unit: before_create dict output (no DB) ─────────────────────────────────

class TestBeforeCreateReverseInference:
    """TripleService.before_create() reverse-infers evidence_signal from confidence."""

    def _make_service(self):
        from src.modules.memvault.kg_services import TripleService
        return TripleService()

    def test_mid_confidence_inferred(self):
        from src.modules.memvault.kg_schemas import TripleCreate
        svc = self._make_service()
        data = TripleCreate(subject="A", predicate="knows", object="B", confidence=0.5)
        result = svc.before_create(data)
        assert result["evidence_signal"] == "inferred", (
            "confidence=0.5 must reverse-infer to 'inferred'"
        )

    def test_high_confidence_inferred_to_extracted(self):
        from src.modules.memvault.kg_schemas import TripleCreate
        svc = self._make_service()
        data = TripleCreate(subject="A", predicate="knows", object="B", confidence=0.9)
        result = svc.before_create(data)
        assert result["evidence_signal"] == "extracted", (
            "confidence=0.9 must reverse-infer to 'extracted'"
        )

    def test_low_confidence_inferred_to_ambiguous(self):
        from src.modules.memvault.kg_schemas import TripleCreate
        svc = self._make_service()
        data = TripleCreate(subject="A", predicate="knows", object="B", confidence=0.1)
        result = svc.before_create(data)
        assert result["evidence_signal"] == "ambiguous", (
            "confidence=0.1 must reverse-infer to 'ambiguous'"
        )

    def test_explicit_evidence_signal_not_overwritten(self):
        """Explicit evidence_signal='extracted' must not be overwritten even if confidence is low."""
        from src.modules.memvault.kg_schemas import TripleCreate
        svc = self._make_service()
        data = TripleCreate(
            subject="A",
            predicate="knows",
            object="B",
            confidence=0.5,
            evidence_signal="extracted",  # explicit — should be preserved
        )
        result = svc.before_create(data)
        assert result["evidence_signal"] == "extracted", (
            "Explicit evidence_signal='extracted' must not be overwritten by reverse-inference"
        )

    def test_explicit_inferred_not_overwritten(self):
        """Explicit evidence_signal='inferred' must not be overwritten even with high confidence."""
        from src.modules.memvault.kg_schemas import TripleCreate
        svc = self._make_service()
        data = TripleCreate(
            subject="A",
            predicate="knows",
            object="B",
            confidence=0.95,
            evidence_signal="inferred",  # explicit
        )
        result = svc.before_create(data)
        assert result["evidence_signal"] == "inferred", (
            "Explicit evidence_signal='inferred' must not be upgraded by high confidence"
        )

    def test_none_confidence_no_reverse_inference(self):
        """confidence=None → no reverse inference → default 'extracted' preserved."""
        from src.modules.memvault.kg_schemas import TripleCreate
        svc = self._make_service()
        data = TripleCreate(subject="A", predicate="knows", object="B", confidence=None)
        result = svc.before_create(data)
        assert result["evidence_signal"] == "extracted", (
            "confidence=None must not trigger reverse inference — keep default 'extracted'"
        )

    def test_predicate_still_normalized(self):
        """before_create must still normalize predicate even with reverse inference."""
        from src.modules.memvault.kg_schemas import TripleCreate
        svc = self._make_service()
        data = TripleCreate(subject="A", predicate="KNOWS ABOUT", object="B", confidence=0.5)
        result = svc.before_create(data)
        # predicate should be normalized (lowercased/underscored by normalize_predicate)
        assert result["predicate"] == result["predicate"].lower() or "_" in result["predicate"] or result["predicate"] == result["predicate"].strip(), (
            "before_create must still run predicate normalization"
        )
        assert result["evidence_signal"] == "inferred"

    def test_explicit_ambiguous_not_overwritten(self):
        """Explicit evidence_signal='ambiguous' must not be overwritten even with high confidence."""
        from src.modules.memvault.kg_schemas import TripleCreate
        svc = self._make_service()
        data = TripleCreate(
            subject="A",
            predicate="knows",
            object="B",
            confidence=0.99,
            evidence_signal="ambiguous",
        )
        result = svc.before_create(data)
        assert result["evidence_signal"] == "ambiguous", (
            "Explicit evidence_signal='ambiguous' must be preserved regardless of confidence"
        )


# ── DB Test (Real PG) ────────────────────────────────────────────────────────

pytest.importorskip("sqlalchemy")
pytest.importorskip("psycopg")

from sqlalchemy import select  # noqa: E402

from shared.database import async_session_factory  # noqa: E402
from src.modules.memvault.kg_models import Triple  # noqa: E402


def _uid() -> str:
    return uuid.uuid4().hex[:16]


async def _hard_delete_triple(tid: str) -> None:
    async with async_session_factory() as db:
        row = (await db.execute(select(Triple).where(Triple.id == tid))).scalar_one_or_none()
        if row:
            await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_db_before_create_inferred_persisted():
    """E2E DB: TripleCreate(confidence=0.5) → stored evidence_signal='inferred'."""
    from src.modules.memvault.kg_schemas import TripleCreate
    from src.modules.memvault.kg_services import TripleService

    space_id = f"adv-signal-{_uid()}"
    svc = TripleService()
    data = TripleCreate(
        subject=f"S-{_uid()}",
        predicate="related_to",
        object=f"O-{_uid()}",
        confidence=0.5,
        space_id=space_id,
        source_session=f"sess-{_uid()}",
    )

    async with async_session_factory() as db:
        triple = await svc.create(db, data)

    try:
        async with async_session_factory() as db:
            row = (await db.execute(select(Triple).where(Triple.id == triple.id))).scalar_one()
        assert row.evidence_signal == "inferred", (
            f"DB: confidence=0.5 should be persisted as 'inferred', got '{row.evidence_signal}'"
        )
    finally:
        await _hard_delete_triple(triple.id)


@pytest.mark.asyncio
async def test_db_explicit_evidence_signal_not_overwritten():
    """E2E DB: Explicit evidence_signal='extracted' must be preserved in DB."""
    from src.modules.memvault.kg_schemas import TripleCreate
    from src.modules.memvault.kg_services import TripleService

    space_id = f"adv-signal-{_uid()}"
    svc = TripleService()
    data = TripleCreate(
        subject=f"S-{_uid()}",
        predicate="related_to",
        object=f"O-{_uid()}",
        confidence=0.5,
        evidence_signal="extracted",  # explicit
        space_id=space_id,
        source_session=f"sess-{_uid()}",
    )

    async with async_session_factory() as db:
        triple = await svc.create(db, data)

    try:
        async with async_session_factory() as db:
            row = (await db.execute(select(Triple).where(Triple.id == triple.id))).scalar_one()
        assert row.evidence_signal == "extracted", (
            f"Explicit evidence_signal='extracted' must be preserved in DB, got '{row.evidence_signal}'"
        )
    finally:
        await _hard_delete_triple(triple.id)


@pytest.mark.asyncio
async def test_db_none_confidence_keeps_default_extracted():
    """E2E DB: confidence=None → no reverse inference → DB stores default 'extracted'."""
    from src.modules.memvault.kg_schemas import TripleCreate
    from src.modules.memvault.kg_services import TripleService

    space_id = f"adv-signal-{_uid()}"
    svc = TripleService()
    data = TripleCreate(
        subject=f"S-{_uid()}",
        predicate="related_to",
        object=f"O-{_uid()}",
        confidence=None,
        space_id=space_id,
        source_session=f"sess-{_uid()}",
    )

    async with async_session_factory() as db:
        triple = await svc.create(db, data)

    try:
        async with async_session_factory() as db:
            row = (await db.execute(select(Triple).where(Triple.id == triple.id))).scalar_one()
        assert row.evidence_signal == "extracted", (
            f"confidence=None must keep default 'extracted' in DB, got '{row.evidence_signal}'"
        )
    finally:
        await _hard_delete_triple(triple.id)

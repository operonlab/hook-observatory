"""supersede_blocks_by_doc — Phase 3 dispatcher tests.

Mock boundaries (六鐵律 #5):
- src.shared.embedding.get_embedding (cross-module entry)
- memory_block_service.qdrant_search (we test the supersede logic that wraps
  it; the search itself is independently covered by memvault's own tests)
- memory_block_service.get_in_space (DB fetch — the test injects fake blocks)

Internal logic (threshold filter, voice=user_lead skip, idempotency on
already-invalidated, audit trail string format) runs real.

六鐵律 disclosure: main-thread author. Mutation-thinking enforced via
killer tests on the four safety guards: threshold, voice, idempotency,
dry_run.
"""

from __future__ import annotations

import asyncio
import types
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from src.modules.memvault.schemas import SupersedeByDocRequest
from src.modules.memvault.services import memory_block_service

# ── Fakes ──────────────────────────────────────────────────────────────


def _fake_block(
    *,
    block_id: str,
    content: str = "stale block content",
    voice: str | None = "dialog",
    invalid_at: datetime | None = None,
    score: float = 0.9,
) -> Any:
    """SemanticSearchResult-shaped wrapper around a MemoryBlock-like."""
    block = MagicMock()
    block.id = block_id
    block.content = content
    block.voice = voice
    block.invalid_at = invalid_at
    block.superseded_by = None
    block.invalidation_reason = None
    item = MagicMock()
    item.block = block
    item.score = score
    return item


@pytest.fixture(autouse=True)
def _patch_externals(monkeypatch):
    """Default: embedding works, qdrant returns []."""
    fake_embed = AsyncMock(return_value=[0.0] * 1024)
    fake_embed_mod = types.ModuleType("src.shared.embedding")
    fake_embed_mod.get_embedding = fake_embed
    monkeypatch.setitem(__import__("sys").modules, "src.shared.embedding", fake_embed_mod)

    # qdrant_search returns ([], meta)
    monkeypatch.setattr(
        memory_block_service, "qdrant_search", AsyncMock(return_value=([], MagicMock()))
    )
    yield {"embed_mod": fake_embed_mod, "embedding": fake_embed}


# ── Schema validation killers ──────────────────────────────────────────


def test_request_defaults():
    r = SupersedeByDocRequest(doc_id="abc", query_text="x")
    assert r.threshold == 0.85
    assert r.top_k == 20
    assert r.dry_run is False
    assert r.doc_title is None


@pytest.mark.parametrize("bad", [0.4, 0.0, -1.0, 1.5, 2.0])
def test_threshold_out_of_range_rejected(bad):
    """Killer: threshold ge=0.5 le=1.0 — out-of-range would either mass-supersede
    (too low) or never supersede (too high), both architectural bugs.
    """
    with pytest.raises(ValidationError):
        SupersedeByDocRequest(doc_id="abc", query_text="x", threshold=bad)


def test_top_k_above_50_rejected():
    with pytest.raises(ValidationError):
        SupersedeByDocRequest(doc_id="abc", query_text="x", top_k=51)


def test_doc_id_empty_rejected():
    with pytest.raises(ValidationError):
        SupersedeByDocRequest(doc_id="", query_text="x")


def test_query_text_empty_rejected():
    with pytest.raises(ValidationError):
        SupersedeByDocRequest(doc_id="abc", query_text="")


# ── Embedding unavailable degradation ──────────────────────────────────


def test_no_embedding_returns_error_no_crash(_patch_externals):
    _patch_externals["embedding"].return_value = []  # empty embedding
    result = asyncio.run(
        memory_block_service.supersede_blocks_by_doc(
            db=MagicMock(), space_id="default", doc_id="abc", query_text="x"
        )
    )
    assert result["superseded"] == []
    assert "error" in result


# ── Threshold filter ───────────────────────────────────────────────────


def test_below_threshold_blocks_excluded(monkeypatch):
    monkeypatch.setattr(
        memory_block_service,
        "qdrant_search",
        AsyncMock(
            return_value=(
                [
                    _fake_block(block_id="below", score=0.7),
                    _fake_block(block_id="above", score=0.9),
                ],
                MagicMock(),
            )
        ),
    )
    monkeypatch.setattr(
        memory_block_service,
        "get_in_space",
        AsyncMock(
            side_effect=lambda db, bid, sid: MagicMock(
                id=bid,
                voice="dialog",
                invalid_at=None,
                invalidation_reason=None,
                superseded_by=None,
            )
        ),
    )

    result = asyncio.run(
        memory_block_service.supersede_blocks_by_doc(
            db=MagicMock(),
            space_id="default",
            doc_id="doc1",
            query_text="x",
            threshold=0.85,
        )
    )
    assert result["superseded"] == ["above"]
    assert "below" not in result["superseded"]


# ── Voice=user_lead safety guard (killer) ──────────────────────────────


def test_user_lead_blocks_never_superseded(monkeypatch):
    """Killer: user-articulated facts must not be auto-invalidated by an
    external doc. A mutation removing the voice check would invalidate the
    user_lead block here, surfacing immediately.
    """
    monkeypatch.setattr(
        memory_block_service,
        "qdrant_search",
        AsyncMock(
            return_value=(
                [
                    _fake_block(block_id="ul", voice="user_lead", score=0.99),
                    _fake_block(block_id="dl", voice="dialog", score=0.99),
                    _fake_block(block_id="al", voice="assistant_lead", score=0.99),
                ],
                MagicMock(),
            )
        ),
    )
    monkeypatch.setattr(
        memory_block_service,
        "get_in_space",
        AsyncMock(
            side_effect=lambda db, bid, sid: MagicMock(
                id=bid,
                voice="ignored",
                invalid_at=None,
                invalidation_reason=None,
                superseded_by=None,
            )
        ),
    )

    result = asyncio.run(
        memory_block_service.supersede_blocks_by_doc(
            db=MagicMock(), space_id="default", doc_id="doc1", query_text="x"
        )
    )
    assert "ul" not in result["superseded"]
    assert "dl" in result["superseded"]
    assert "al" in result["superseded"]


# ── Idempotency: already-invalidated blocks skipped ────────────────────


def test_already_invalidated_blocks_skipped(monkeypatch):
    """Killer: re-running supersede after a crash must not double-invalidate
    or churn invalidation_reason on already-superseded rows.
    """
    monkeypatch.setattr(
        memory_block_service,
        "qdrant_search",
        AsyncMock(
            return_value=(
                [
                    _fake_block(
                        block_id="dead", invalid_at=datetime(2026, 1, 1, tzinfo=UTC), score=0.99
                    ),
                    _fake_block(block_id="alive", invalid_at=None, score=0.99),
                ],
                MagicMock(),
            )
        ),
    )
    monkeypatch.setattr(
        memory_block_service,
        "get_in_space",
        AsyncMock(
            side_effect=lambda db, bid, sid: MagicMock(
                id=bid,
                voice="dialog",
                invalid_at=None,
                invalidation_reason=None,
                superseded_by=None,
            )
        ),
    )

    result = asyncio.run(
        memory_block_service.supersede_blocks_by_doc(
            db=MagicMock(), space_id="default", doc_id="doc1", query_text="x"
        )
    )
    assert "dead" not in result["superseded"]
    assert "alive" in result["superseded"]


# ── dry_run path: no DB mutation ───────────────────────────────────────


def test_dry_run_returns_candidates_without_invalidating(monkeypatch):
    """Killer: dry_run must surface candidates but NOT touch any row."""
    get_in_space_mock = AsyncMock()
    monkeypatch.setattr(memory_block_service, "get_in_space", get_in_space_mock)
    monkeypatch.setattr(
        memory_block_service,
        "qdrant_search",
        AsyncMock(
            return_value=(
                [_fake_block(block_id="cand", score=0.9)],
                MagicMock(),
            )
        ),
    )

    result = asyncio.run(
        memory_block_service.supersede_blocks_by_doc(
            db=MagicMock(),
            space_id="default",
            doc_id="doc1",
            query_text="x",
            dry_run=True,
        )
    )
    assert result["superseded"] == []
    assert len(result["dry_run_matches"]) == 1
    assert result["dry_run_matches"][0]["block_id"] == "cand"
    # invalidation must NOT have been attempted
    assert get_in_space_mock.call_count == 0


# ── Audit trail format ─────────────────────────────────────────────────


def test_invalidation_reason_includes_doc_id_and_title(monkeypatch):
    captured: list[Any] = []

    def _fake_block_factory(db, bid, sid):
        b = MagicMock()
        b.id = bid
        b.voice = "dialog"
        b.invalid_at = None
        b.invalidation_reason = None
        b.superseded_by = None
        captured.append(b)
        return b

    monkeypatch.setattr(
        memory_block_service,
        "qdrant_search",
        AsyncMock(
            return_value=(
                [_fake_block(block_id="x", score=0.9)],
                MagicMock(),
            )
        ),
    )
    monkeypatch.setattr(
        memory_block_service,
        "get_in_space",
        AsyncMock(side_effect=_fake_block_factory),
    )

    asyncio.run(
        memory_block_service.supersede_blocks_by_doc(
            db=MagicMock(),
            space_id="default",
            doc_id="019e2bfa",
            query_text="x",
            doc_title="memvault overview",
        )
    )
    assert len(captured) == 1
    block = captured[0]
    # superseded_by stays NULL — it's an FK to blocks.id (block→block path).
    # Doc identity lives in invalidation_reason.
    assert block.superseded_by is None
    assert "superseded_by_doc:019e2bfa" in (block.invalidation_reason or "")
    assert "memvault overview" in (block.invalidation_reason or "")
    assert block.invalid_at is not None

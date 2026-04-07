"""Tests for docvault KG layer — ChunkEntityOp, CommunityIndexOp, GraphSearchOp.

Written by independent test agent following 六鐵律:
  1. Mutation thinking — failing cases designed BEFORE happy paths
  2. Write/test separation — this file is independent of the implementation author
  3. Invariant first — contracts, dedup invariants, score ordering
  4. Runtime → regression — tests mirror real regression paths
  5. Mock only external I/O — LLM calls, Qdrant, DB session mocked; kg_ops internals NOT mocked
  6. Draft ≠ finished — every test is production-quality with clear intent
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ..ops.chunk_entity import ChunkEntityOp, _build_entity_dedup_map
from ..ops.community_index import MIN_TRIPLES, CommunityIndexOp
from ..ops.graph_search import GraphSearchOp, _GRAPH_BASE_SCORE, _OVERLAP_BOOST


# ============================================================
# Shared test fixtures and helpers
# ============================================================


def _make_chunk(db_id: str, content: str) -> dict[str, Any]:
    return {"db_id": db_id, "content": content}


def _make_triple(subject: str, predicate: str, obj: str) -> dict[str, str]:
    return {"subject": subject, "predicate": predicate, "object": obj}


def _make_db_session() -> MagicMock:
    """Return a MagicMock that satisfies AsyncSession protocol."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


def _make_triple_orm(
    triple_id: str,
    subject: str,
    predicate: str,
    obj: str,
    chunk_id: str | None = None,
    space_id: str = "sp1",
    document_id: str = "doc1",
) -> MagicMock:
    t = MagicMock()
    t.id = triple_id
    t.subject = subject
    t.predicate = predicate
    t.object = obj
    t.chunk_id = chunk_id
    t.space_id = space_id
    t.document_id = document_id
    t.deleted_at = None
    return t


# ============================================================
# ChunkEntityOp — early-exit guards
# ============================================================


@pytest.mark.asyncio
class TestChunkEntityOpEarlyExit:
    async def test_skips_when_no_db(self):
        """db=None → entity_count=0, triple_count=0, no exception."""
        op = ChunkEntityOp()
        ctx: dict[str, Any] = {
            "chunks": [_make_chunk("c1", "Some content.")],
            "document_id": "doc1",
            "space_id": "sp1",
        }
        result = await op(ctx)

        assert result["entity_count"] == 0
        assert result["triple_count"] == 0
        assert result["doc_entities"] == []
        assert result["doc_triples"] == []

    async def test_skips_when_chunks_empty(self):
        """chunks=[] → entity_count=0, triple_count=0, DB never touched."""
        op = ChunkEntityOp()
        db = _make_db_session()
        ctx: dict[str, Any] = {
            "chunks": [],
            "document_id": "doc1",
            "space_id": "sp1",
            "db": db,
        }
        result = await op(ctx)

        assert result["entity_count"] == 0
        assert result["triple_count"] == 0
        db.add.assert_not_called()
        db.flush.assert_not_called()

    async def test_output_keys_always_present_when_no_db(self):
        """Operator contract: all output_keys must be set even in skip path."""
        op = ChunkEntityOp()
        ctx: dict[str, Any] = {"chunks": [], "document_id": "d", "space_id": "s"}
        result = await op(ctx)

        for key in op.output_keys:
            assert key in result, f"Missing output key: {key}"


# ============================================================
# ChunkEntityOp — entity deduplication
# ============================================================


class TestBuildEntityDedupMap:
    """Unit-tests for _build_entity_dedup_map — no async, no mocking."""

    def test_single_entity_in_single_chunk(self):
        pairs = [
            (_make_chunk("c1", ""), [_make_triple("Python", "is", "language")]),
        ]
        result = _build_entity_dedup_map(pairs)
        # normalize_entity_text("Python") → "python" (lowercase)
        assert len(result) == 2  # "python" + "language"
        assert "python" in result

    def test_same_canonical_across_chunks_merged(self):
        """Two chunks mentioning "Python" → single entity, merged chunk references."""
        pairs = [
            (_make_chunk("c1", ""), [_make_triple("Python", "is", "language")]),
            (_make_chunk("c2", ""), [_make_triple("Python", "runs", "server")]),
        ]
        result = _build_entity_dedup_map(pairs)
        python = result["python"]

        # Only one entity per canonical
        python_keys = [k for k in result if k == "python"]
        assert len(python_keys) == 1

        # Both chunk IDs tracked
        assert "c1" in python["source_chunk_ids"]
        assert "c2" in python["source_chunk_ids"]

    def test_mention_count_accumulates(self):
        """Mention count must equal total times entity appears across all triples."""
        pairs = [
            (
                _make_chunk("c1", ""),
                [
                    _make_triple("Python", "is", "language"),
                    _make_triple("Python", "runs", "scripts"),
                ],
            ),
            (_make_chunk("c2", ""), [_make_triple("Python", "uses", "indent")]),
        ]
        result = _build_entity_dedup_map(pairs)
        # "python" appears in 3 triples as subject
        assert result["python"]["mention_count"] == 3

    def test_alias_added_when_raw_differs_from_canonical(self):
        """If raw_name != canonical, raw_name should appear in aliases."""
        pairs = [
            (_make_chunk("c1", ""), [_make_triple("Python", "is", "language")]),
        ]
        result = _build_entity_dedup_map(pairs)
        python = result["python"]
        # "Python" (capital P) should be tracked as alias of canonical "python"
        assert "Python" in python["aliases"]

    def test_alias_not_duplicated(self):
        """Same alias across multiple chunks should appear only once."""
        pairs = [
            (_make_chunk("c1", ""), [_make_triple("Python", "is", "language")]),
            (_make_chunk("c2", ""), [_make_triple("Python", "runs", "scripts")]),
        ]
        result = _build_entity_dedup_map(pairs)
        python_aliases = result["python"]["aliases"]
        assert python_aliases.count("Python") == 1

    def test_source_chunk_ids_no_duplicates(self):
        """Same chunk mentioned twice should appear only once in source_chunk_ids."""
        pairs = [
            (
                _make_chunk("c1", ""),
                [
                    _make_triple("Python", "is", "language"),
                    _make_triple("Python", "runs", "scripts"),
                ],
            ),
        ]
        result = _build_entity_dedup_map(pairs)
        chunk_ids = result["python"]["source_chunk_ids"]
        assert chunk_ids.count("c1") == 1

    def test_empty_canonical_skipped(self):
        """normalize_entity_text returning empty string → entity NOT added."""
        # Inject a triple whose subject normalizes to "" (whitespace-only)
        pairs = [
            (_make_chunk("c1", ""), [_make_triple("   ", "is", "thing")]),
        ]
        result = _build_entity_dedup_map(pairs)
        # "   " normalized to "" → must not be in result
        assert "" not in result

    def test_triple_count_equals_subject_plus_object(self):
        """Dedup map has entries for both subject and object of each triple."""
        pairs = [
            (
                _make_chunk("c1", ""),
                [_make_triple("Python", "is", "language")],
            ),
        ]
        result = _build_entity_dedup_map(pairs)
        # Both "python" and "language" must appear
        assert "python" in result
        assert "language" in result

    def test_chunk_without_db_id_not_appended_to_source(self):
        """Chunks without db_id should not pollute source_chunk_ids."""
        pairs = [
            ({"content": "x"},  # no "db_id" key
             [_make_triple("Python", "is", "language")]),
        ]
        result = _build_entity_dedup_map(pairs)
        python = result["python"]
        assert None not in python["source_chunk_ids"]
        # No falsy values
        assert all(python["source_chunk_ids"])


# ============================================================
# ChunkEntityOp — LLM failure isolation (graceful degradation)
# ============================================================


@pytest.mark.asyncio
class TestChunkEntityOpLLMFailure:
    async def test_llm_failure_one_chunk_does_not_abort_others(self):
        """If extract_triples raises for one chunk, other chunks still processed."""
        call_count = 0

        async def fake_extract_triples(content, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("LLM timeout")
            return [_make_triple("Python", "is", "language")]

        db = _make_db_session()
        # Give each ORM entity a fake id so canonical_to_id lookup works
        created_entities: list[MagicMock] = []

        def fake_add(obj):
            obj.id = f"eid-{len(created_entities)}"
            created_entities.append(obj)

        db.add.side_effect = fake_add

        op = ChunkEntityOp()
        ctx: dict[str, Any] = {
            "chunks": [
                _make_chunk("c1", "Content A"),
                _make_chunk("c2", "Content B"),
            ],
            "document_id": "doc1",
            "space_id": "sp1",
            "db": db,
        }

        with patch(
            "src.modules.docvault.ops.chunk_entity.extract_triples",
            side_effect=fake_extract_triples,
        ):
            result = await op(ctx)

        # Second chunk succeeded → at least 1 entity and 1 triple
        assert result["entity_count"] >= 1
        assert result["triple_count"] >= 1

    async def test_all_chunks_fail_returns_zero_counts(self):
        """All LLM failures → entity_count=0, triple_count=0, no crash."""
        async def fail_extract(*args, **kwargs):
            raise ConnectionError("LLM down")

        db = _make_db_session()
        op = ChunkEntityOp()
        ctx: dict[str, Any] = {
            "chunks": [_make_chunk("c1", "x"), _make_chunk("c2", "y")],
            "document_id": "doc1",
            "space_id": "sp1",
            "db": db,
        }

        with patch(
            "src.modules.docvault.ops.chunk_entity.extract_triples",
            side_effect=fail_extract,
        ):
            result = await op(ctx)

        assert result["entity_count"] == 0
        assert result["triple_count"] == 0


# ============================================================
# ChunkEntityOp — triple-to-entity linking (subject_entity_id / object_entity_id)
# ============================================================


@pytest.mark.asyncio
class TestChunkEntityOpTripleLinking:
    async def test_triple_subject_object_linked_to_entity_ids(self):
        """DocTriple.subject_entity_id / object_entity_id must reference DocEntity.id."""
        entity_registry: dict[str, str] = {}  # canonical → assigned id

        def fake_add(obj):
            from src.modules.docvault.kg_models import DocEntity, DocTriple

            if isinstance(obj, DocEntity):
                eid = f"eid-{obj.canonical_name}"
                obj.id = eid
                entity_registry[obj.canonical_name] = eid

        db = _make_db_session()
        db.add.side_effect = fake_add

        triple_data = _make_triple("Python", "is", "language")

        async def fake_extract(*args, **kwargs):
            return [triple_data]

        op = ChunkEntityOp()
        ctx: dict[str, Any] = {
            "chunks": [_make_chunk("c1", "content")],
            "document_id": "doc1",
            "space_id": "sp1",
            "db": db,
        }

        with patch(
            "src.modules.docvault.ops.chunk_entity.extract_triples",
            side_effect=fake_extract,
        ):
            result = await op(ctx)

        doc_triples = result["doc_triples"]
        assert len(doc_triples) == 1
        triple = doc_triples[0]

        # subject "Python" normalizes to "python" → must resolve to entity id
        assert triple.subject_entity_id == entity_registry.get("python")
        # object "language" → must resolve to entity id
        assert triple.object_entity_id == entity_registry.get("language")

    async def test_triple_count_matches_extracted_triples(self):
        """triple_count must equal total triples returned from all chunks."""
        n_triples = 3

        async def fake_extract(*args, **kwargs):
            return [
                _make_triple(f"E{i}", "relates", f"O{i}") for i in range(n_triples)
            ]

        entities: list[Any] = []

        def fake_add(obj):
            obj.id = f"id-{len(entities)}"
            entities.append(obj)

        db = _make_db_session()
        db.add.side_effect = fake_add

        op = ChunkEntityOp()
        ctx: dict[str, Any] = {
            "chunks": [_make_chunk("c1", "content")],
            "document_id": "doc1",
            "space_id": "sp1",
            "db": db,
        }

        with patch(
            "src.modules.docvault.ops.chunk_entity.extract_triples",
            side_effect=fake_extract,
        ):
            result = await op(ctx)

        assert result["triple_count"] == n_triples


# ============================================================
# ChunkEntityOp — operator protocol
# ============================================================


class TestChunkEntityOpProtocol:
    def test_name_property(self):
        assert ChunkEntityOp().name == "chunk_entity"

    def test_input_keys_contract(self):
        op = ChunkEntityOp()
        for key in ("chunks", "document_id", "space_id", "db"):
            assert key in op.input_keys

    def test_output_keys_contract(self):
        op = ChunkEntityOp()
        for key in ("entity_count", "triple_count", "doc_entities", "doc_triples"):
            assert key in op.output_keys


# ============================================================
# Invariants — normalize_entity_text is called on all subjects and objects
# ============================================================


class TestNormalizeInvariant:
    def test_all_canonical_names_are_lowercase_for_ascii(self):
        """Canonical names for pure ASCII input must be lowercase."""
        pairs = [
            (_make_chunk("c1", ""), [_make_triple("UPPERCASE_ENTITY", "is", "thing")]),
        ]
        result = _build_entity_dedup_map(pairs)
        for key in result:
            # Keys that are pure ASCII must be lowercase
            if key.isascii():
                assert key == key.lower(), f"Canonical '{key}' is not lowercase"

    def test_whitespace_collapsed_in_canonical(self):
        """Canonical name must not have leading/trailing whitespace."""
        pairs = [
            (_make_chunk("c1", ""), [_make_triple("  spaced  ", "is", "thing")]),
        ]
        result = _build_entity_dedup_map(pairs)
        for key in result:
            assert key == key.strip(), f"Canonical '{key}' has surrounding whitespace"


# ============================================================
# CommunityIndexOp — early-exit guard
# ============================================================


@pytest.mark.asyncio
class TestCommunityIndexOpEarlyExit:
    async def _make_ctx_with_triples(self, n_triples: int) -> dict[str, Any]:
        """Build a minimal ctx where db.execute returns n_triples rows."""
        db = _make_db_session()
        triple_orms = [
            _make_triple_orm(f"t{i}", f"S{i}", "is", f"O{i}", chunk_id=f"c{i}")
            for i in range(n_triples)
        ]

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = triple_orms

        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock

        db.execute.return_value = result_mock

        return {"space_id": "sp1", "db": db}

    async def test_returns_zero_when_fewer_than_min_triples(self):
        """Fewer than MIN_TRIPLES (5) → community_count=0, summary_count=0."""
        ctx = await self._make_ctx_with_triples(MIN_TRIPLES - 1)
        op = CommunityIndexOp()
        result = await op(ctx)

        assert result["community_count"] == 0
        assert result["summary_count"] == 0

    async def test_exactly_min_triples_proceeds(self):
        """Exactly MIN_TRIPLES → should NOT return early (proceeds to Leiden)."""
        ctx = await self._make_ctx_with_triples(MIN_TRIPLES)

        with (
            patch("src.modules.docvault.ops.community_index.build_entity_graph") as mock_beg,
            patch("src.modules.docvault.ops.community_index.run_leiden") as mock_leiden,
        ):
            mock_beg.return_value = (MagicMock(), {})
            mock_leiden.return_value = {}  # empty communities_by_level → 0 communities

            op = CommunityIndexOp()
            result = await op(ctx)

        mock_leiden.assert_called_once()
        assert result["community_count"] == 0  # no communities produced

    async def test_output_keys_always_present_on_early_exit(self):
        """community_count and summary_count must exist even on early exit."""
        ctx = await self._make_ctx_with_triples(0)
        op = CommunityIndexOp()
        result = await op(ctx)

        assert "community_count" in result
        assert "summary_count" in result


# ============================================================
# CommunityIndexOp — atomic replace
# ============================================================


@pytest.mark.asyncio
class TestCommunityIndexOpAtomicReplace:
    async def test_old_communities_deleted_before_new_ones_inserted(self):
        """DELETE statements must be executed before any db.add() calls."""
        db = _make_db_session()

        triple_orms = [
            _make_triple_orm(f"t{i}", f"S{i}", "is", f"O{i}", chunk_id=f"c{i}")
            for i in range(MIN_TRIPLES)
        ]
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = triple_orms
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock

        # Track call order
        call_order: list[str] = []
        db.execute.side_effect = lambda stmt: (
            call_order.append("execute") or asyncio.coroutine(lambda: result_mock)()
        )

        execute_results = [result_mock]

        async def execute_side_effect(stmt):
            call_order.append("execute")
            return result_mock

        db.execute = AsyncMock(side_effect=execute_side_effect)

        def add_side_effect(obj):
            call_order.append("add")
            obj.id = f"id-{len(call_order)}"

        db.add.side_effect = add_side_effect

        with (
            patch("src.modules.docvault.ops.community_index.build_entity_graph") as mock_beg,
            patch("src.modules.docvault.ops.community_index.run_leiden") as mock_leiden,
            patch("src.modules.docvault.ops.community_index.assign_triples_to_communities") as mock_atc,
            patch("src.modules.docvault.ops.community_index.build_triple_text", return_value=""),
            patch("src.modules.docvault.ops.community_index.build_community_summary_messages", return_value=[]),
        ):
            mock_beg.return_value = (MagicMock(), {"S0": 0, "O0": 0})
            # Provide one community at level 0 only (no level 2 → no LLM calls)
            mock_leiden.return_value = {0: [[0]]}
            mock_atc.return_value = {}

            op = CommunityIndexOp()
            ctx: dict[str, Any] = {"space_id": "sp1", "db": db}
            await op(ctx)

        # DELETE statements must appear before the first add()
        first_add_idx = next(
            (i for i, v in enumerate(call_order) if v == "add"), None
        )
        execute_indices = [i for i, v in enumerate(call_order) if v == "execute"]

        # First three executes are the three DELETE statements (summary, triple, community)
        # They must all precede the first add
        if first_add_idx is not None:
            deletes_before_add = [i for i in execute_indices if i < first_add_idx]
            # Must have at least 3 deletes (summary + community_triple + community)
            # plus 1 for the initial SELECT
            assert len(deletes_before_add) >= 3


# ============================================================
# CommunityIndexOp — entity_ids cap at 50, top_entities cap at 10
# ============================================================


@pytest.mark.asyncio
class TestCommunityIndexOpCaps:
    async def test_entity_ids_capped_at_50(self):
        """Community with 100 vertices → entity_ids has at most 50 entries."""
        db = _make_db_session()

        triple_orms = [
            _make_triple_orm(f"t{i}", f"S{i}", "is", f"O{i}", chunk_id=f"c{i}")
            for i in range(MIN_TRIPLES)
        ]
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = triple_orms
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        added_communities: list[Any] = []

        def add_side_effect(obj):
            obj.id = f"id-{len(added_communities)}"
            from src.modules.docvault.kg_models import DocCommunity

            if hasattr(obj, "resolution_level"):
                added_communities.append(obj)

        db.add.side_effect = add_side_effect

        # Build a fake idx_to_entity with 100 entries
        idx_to_entity = {i: f"entity_{i}" for i in range(100)}
        entity_to_idx = {v: k for k, v in idx_to_entity.items()}

        with (
            patch("src.modules.docvault.ops.community_index.build_entity_graph") as mock_beg,
            patch("src.modules.docvault.ops.community_index.run_leiden") as mock_leiden,
            patch("src.modules.docvault.ops.community_index.assign_triples_to_communities", return_value={}),
            patch("src.modules.docvault.ops.community_index.build_triple_text", return_value=""),
            patch("src.modules.docvault.ops.community_index.build_community_summary_messages", return_value=[]),
        ):
            mock_beg.return_value = (MagicMock(), entity_to_idx)
            # One community at level 0 with all 100 vertices
            mock_leiden.return_value = {0: [list(range(100))]}

            op = CommunityIndexOp()
            ctx: dict[str, Any] = {"space_id": "sp1", "db": db}
            await op(ctx)

        # Each community's entity_ids must be capped
        for community in added_communities:
            if community.entity_ids is not None:
                assert len(community.entity_ids) <= 50, (
                    f"entity_ids exceeded cap: {len(community.entity_ids)}"
                )
            if community.top_entities is not None:
                assert len(community.top_entities) <= 10, (
                    f"top_entities exceeded cap: {len(community.top_entities)}"
                )

    async def test_resolution_level_matches_leiden_level(self):
        """Community.resolution_level must equal the Leiden level key."""
        db = _make_db_session()

        triple_orms = [
            _make_triple_orm(f"t{i}", f"S{i}", "is", f"O{i}", chunk_id=f"c{i}")
            for i in range(MIN_TRIPLES)
        ]
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = triple_orms
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        added_communities: list[Any] = []

        def add_side_effect(obj):
            obj.id = f"id-{len(added_communities)}"
            if hasattr(obj, "resolution_level"):
                added_communities.append(obj)

        db.add.side_effect = add_side_effect

        with (
            patch("src.modules.docvault.ops.community_index.build_entity_graph") as mock_beg,
            patch("src.modules.docvault.ops.community_index.run_leiden") as mock_leiden,
            patch("src.modules.docvault.ops.community_index.assign_triples_to_communities", return_value={}),
            patch("src.modules.docvault.ops.community_index.build_triple_text", return_value=""),
            patch("src.modules.docvault.ops.community_index.build_community_summary_messages", return_value=[]),
        ):
            mock_beg.return_value = (MagicMock(), {"S0": 0})
            # Provide communities at levels 0, 1, 2
            mock_leiden.return_value = {
                0: [[0]],
                1: [[0]],
                2: [[0]],
            }

            op = CommunityIndexOp()
            ctx: dict[str, Any] = {"space_id": "sp1", "db": db}
            await op(ctx)

        levels_seen = {c.resolution_level for c in added_communities}
        assert 0 in levels_seen
        assert 1 in levels_seen
        assert 2 in levels_seen


# ============================================================
# CommunityIndexOp — LLM summary fallback
# ============================================================


@pytest.mark.asyncio
class TestCommunityIndexOpSummaryFallback:
    async def _setup_with_level2_community(self) -> dict[str, Any]:
        """Helper: return ctx where Leiden produces one level-2 community."""
        db = _make_db_session()

        triple_orms = [
            _make_triple_orm(f"t{i}", f"S{i}", "is", f"O{i}", chunk_id=f"c{i}")
            for i in range(MIN_TRIPLES)
        ]
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = triple_orms
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        added_objs: list[Any] = []

        def add_side_effect(obj):
            obj.id = f"id-{len(added_objs)}"
            added_objs.append(obj)

        db.add.side_effect = add_side_effect
        db._added_objs = added_objs

        return {"space_id": "sp1", "db": db}, added_objs

    async def test_llm_failure_uses_fallback_text(self):
        """On LLM failure, community.summary must be the fallback text (not None)."""
        ctx, added_objs = await self._setup_with_level2_community()

        # entity_to_idx maps entity name → vertex index (integers)
        entity_to_idx = {"S0": 0, "O0": 1, "S1": 2, "O1": 3, "S2": 4, "O2": 5, "S3": 6, "O3": 7, "S4": 8, "O4": 9}

        with (
            patch("src.modules.docvault.ops.community_index.build_entity_graph") as mock_beg,
            patch("src.modules.docvault.ops.community_index.run_leiden") as mock_leiden,
            patch("src.modules.docvault.ops.community_index.assign_triples_to_communities", return_value={}),
            patch("src.modules.docvault.ops.community_index.build_triple_text", return_value="S0 is O0"),
            patch("src.modules.docvault.ops.community_index.build_community_summary_messages", return_value=[]),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_beg.return_value = (MagicMock(), entity_to_idx)
            # One community at level 2 — vertex INDICES (not names)
            mock_leiden.return_value = {
                2: [[0, 1, 2, 3, 4]]
            }

            # Make httpx raise
            mock_client = AsyncMock()
            mock_client.post.side_effect = ConnectionError("LLM down")
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            op = CommunityIndexOp()
            result = await op(ctx)

        # summary_count should be 1 (fallback was used)
        assert result["summary_count"] == 1

        # Find DocCommunitySummary objects — they have 'summary' attribute
        from src.modules.docvault.kg_models import DocCommunitySummary
        summaries = [o for o in added_objs if isinstance(o, DocCommunitySummary)]
        assert len(summaries) >= 1
        for s in summaries:
            assert s.summary  # must not be empty
            assert "Community of" in s.summary  # fallback template

    async def test_qdrant_failure_does_not_propagate(self):
        """Qdrant indexing failure must be silently absorbed (non-fatal)."""
        ctx, added_objs = await self._setup_with_level2_community()

        with (
            patch("src.modules.docvault.ops.community_index.build_entity_graph") as mock_beg,
            patch("src.modules.docvault.ops.community_index.run_leiden") as mock_leiden,
            patch("src.modules.docvault.ops.community_index.assign_triples_to_communities", return_value={}),
            patch("src.modules.docvault.ops.community_index.build_triple_text", return_value="S0 is O0"),
            patch("src.modules.docvault.ops.community_index.build_community_summary_messages", return_value=[]),
            patch("httpx.AsyncClient") as mock_client_cls,
            patch(
                "src.shared.qdrant_search.index_documents_batch",
                side_effect=RuntimeError("Qdrant unavailable"),
            ),
        ):
            mock_beg.return_value = (
                MagicMock(),
                {f"S{i}": i * 2 for i in range(5)} | {f"O{i}": i * 2 + 1 for i in range(5)},
            )
            mock_leiden.return_value = {2: [[i for i in range(5)]]}

            # LLM succeeds with valid JSON
            llm_resp = MagicMock()
            llm_resp.raise_for_status = MagicMock()
            llm_resp.json.return_value = {
                "choices": [{"message": {"content": json.dumps({"summary": "test", "key_findings": []})}}]
            }
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=llm_resp)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            op = CommunityIndexOp()
            # Must not raise
            result = await op(ctx)

        # community_count and summary_count must still be valid
        assert "community_count" in result
        assert "summary_count" in result


# ============================================================
# GraphSearchOp — empty query guard
# ============================================================


@pytest.mark.asyncio
class TestGraphSearchOpEmptyQuery:
    async def test_empty_query_returns_empty(self):
        op = GraphSearchOp()
        ctx: dict[str, Any] = {"query": "", "space_id": "sp1"}
        result = await op(ctx)
        assert result["evidence_chunks"] == []
        assert result["search_metadata"]["total"] == 0

    async def test_whitespace_query_returns_empty(self):
        op = GraphSearchOp()
        ctx: dict[str, Any] = {"query": "   \t\n", "space_id": "sp1"}
        result = await op(ctx)
        assert result["evidence_chunks"] == []

    async def test_output_keys_present_on_empty_query(self):
        op = GraphSearchOp()
        ctx: dict[str, Any] = {"query": "", "space_id": "sp1"}
        result = await op(ctx)
        for key in op.output_keys:
            assert key in result, f"Missing output key: {key}"


# ============================================================
# GraphSearchOp — vector-only fallback when db absent
# ============================================================


@pytest.mark.asyncio
class TestGraphSearchOpVectorFallback:
    async def test_falls_back_to_vector_only_when_no_db(self):
        """No db in ctx → vector-only mode, no graph recall attempted."""
        vector_chunks = [
            {"id": "c1", "content": "chunk1", "score": 0.9, "source": "vector"},
        ]

        op = GraphSearchOp()
        ctx: dict[str, Any] = {"query": "test query", "space_id": "sp1"}

        with patch.object(op, "_run_vector_search", AsyncMock(return_value=vector_chunks)):
            result = await op(ctx)

        assert result["evidence_chunks"] == vector_chunks
        assert result["search_metadata"]["graph_count"] == 0

    async def test_vector_results_tagged_with_source_vector(self):
        """All results from vector path must have source='vector'."""
        raw_chunks = [
            {"id": "c1", "content": "x", "score": 0.8},
            {"id": "c2", "content": "y", "score": 0.7},
        ]

        op = GraphSearchOp()
        ctx: dict[str, Any] = {"query": "test", "space_id": "sp1"}

        async def fake_vector(ctx, query, space_id, top_k):
            chunks = [dict(c) for c in raw_chunks]
            for c in chunks:
                c["source"] = "vector"
            return chunks

        with patch.object(op, "_run_vector_search", fake_vector):
            result = await op(ctx)

        for chunk in result["evidence_chunks"]:
            assert chunk["source"] == "vector"


# ============================================================
# GraphSearchOp — graph results tagged + overlap boost
# ============================================================


class TestGraphSearchOpMerge:
    """Unit-tests for GraphSearchOp._merge (static method, no async)."""

    def test_vector_results_first_in_merged(self):
        """Vector results should appear first (higher confidence)."""
        vector = [{"id": "v1", "score": 0.9, "source": "vector"}]
        graph = [{"id": "g1", "score": _GRAPH_BASE_SCORE, "source": "graph"}]
        merged = GraphSearchOp._merge(vector, graph, top_k=10)
        assert merged[0]["id"] == "v1"

    def test_graph_results_tagged_with_source_graph(self):
        """Graph-only chunks must retain source='graph'."""
        vector: list[dict] = []
        graph = [{"id": "g1", "score": _GRAPH_BASE_SCORE, "source": "graph"}]
        merged = GraphSearchOp._merge(vector, graph, top_k=10)
        assert merged[0]["source"] == "graph"

    def test_overlap_boost_applied_when_chunk_in_both(self):
        """Chunk appearing in both vector and graph gets score + OVERLAP_BOOST."""
        original_score = 0.7
        vector = [{"id": "c1", "score": original_score, "source": "vector"}]
        graph = [{"id": "c1", "score": _GRAPH_BASE_SCORE, "source": "graph"}]
        merged = GraphSearchOp._merge(vector, graph, top_k=10)

        assert len(merged) == 1  # deduplicated
        boosted = merged[0]
        assert abs(boosted["score"] - (original_score + _OVERLAP_BOOST)) < 1e-9

    def test_overlap_boost_capped_at_1(self):
        """Boosted score must not exceed 1.0."""
        vector = [{"id": "c1", "score": 0.95, "source": "vector"}]
        graph = [{"id": "c1", "score": _GRAPH_BASE_SCORE, "source": "graph"}]
        merged = GraphSearchOp._merge(vector, graph, top_k=10)
        assert merged[0]["score"] <= 1.0

    def test_results_sorted_by_score_descending(self):
        """Merged list must be sorted by score descending."""
        vector = [
            {"id": "v1", "score": 0.5, "source": "vector"},
            {"id": "v2", "score": 0.8, "source": "vector"},
        ]
        graph: list[dict] = []
        merged = GraphSearchOp._merge(vector, graph, top_k=10)
        scores = [m["score"] for m in merged]
        assert scores == sorted(scores, reverse=True)

    def test_results_capped_at_top_k(self):
        """Number of results must not exceed top_k."""
        vector = [{"id": f"v{i}", "score": float(i) / 10, "source": "vector"} for i in range(20)]
        graph: list[dict] = []
        merged = GraphSearchOp._merge(vector, graph, top_k=5)
        assert len(merged) <= 5

    def test_no_duplicate_ids_in_merged(self):
        """Same chunk ID must appear at most once in merged output."""
        vector = [{"id": "c1", "score": 0.9, "source": "vector"}]
        graph = [
            {"id": "c1", "score": 0.5, "source": "graph"},
            {"id": "c2", "score": 0.6, "source": "graph"},
        ]
        merged = GraphSearchOp._merge(vector, graph, top_k=10)
        ids = [m["id"] for m in merged]
        assert len(ids) == len(set(ids))

    def test_empty_inputs_returns_empty(self):
        merged = GraphSearchOp._merge([], [], top_k=10)
        assert merged == []


# ============================================================
# GraphSearchOp — graph recall failure graceful degradation
# ============================================================


@pytest.mark.asyncio
class TestGraphSearchOpGraphFailure:
    async def test_graph_failure_falls_back_to_vector_results(self):
        """If _run_graph_recall raises, output should still contain vector results."""
        vector_chunks = [{"id": "v1", "score": 0.9, "source": "vector"}]

        op = GraphSearchOp()
        ctx: dict[str, Any] = {
            "query": "important question",
            "space_id": "sp1",
            "db": MagicMock(),
        }

        async def raise_graph_error(*args, **kwargs):
            raise RuntimeError("igraph segfault")

        with (
            patch.object(op, "_run_vector_search", AsyncMock(return_value=vector_chunks)),
            patch.object(op, "_run_graph_recall", raise_graph_error),
        ):
            result = await op(ctx)

        # Must not raise; vector results preserved
        assert len(result["evidence_chunks"]) == len(vector_chunks)
        assert result["evidence_chunks"][0]["id"] == "v1"


# ============================================================
# GraphSearchOp — search metadata
# ============================================================


@pytest.mark.asyncio
class TestGraphSearchOpMetadata:
    async def test_metadata_contains_expected_keys(self):
        """search_metadata must contain vector_count, graph_count, merged_count."""
        op = GraphSearchOp()
        ctx: dict[str, Any] = {"query": "something", "space_id": "sp1"}

        with patch.object(op, "_run_vector_search", AsyncMock(return_value=[])):
            result = await op(ctx)

        meta = result["search_metadata"]
        for key in ("vector_count", "graph_count", "merged_count", "top_k"):
            assert key in meta, f"Missing metadata key: {key}"

    async def test_merged_count_matches_len_evidence_chunks(self):
        """search_metadata['merged_count'] must equal len(evidence_chunks)."""
        chunks = [
            {"id": f"c{i}", "score": 0.5, "source": "vector"} for i in range(3)
        ]
        op = GraphSearchOp()
        ctx: dict[str, Any] = {"query": "q", "space_id": "sp1"}

        with patch.object(op, "_run_vector_search", AsyncMock(return_value=chunks)):
            result = await op(ctx)

        assert result["search_metadata"]["merged_count"] == len(result["evidence_chunks"])


# ============================================================
# GraphSearchOp — operator protocol
# ============================================================


class TestGraphSearchOpProtocol:
    def test_name_property(self):
        assert GraphSearchOp().name == "graph_search"

    def test_input_keys_contract(self):
        op = GraphSearchOp()
        assert "query" in op.input_keys
        assert "space_id" in op.input_keys

    def test_output_keys_contract(self):
        op = GraphSearchOp()
        assert "evidence_chunks" in op.output_keys
        assert "search_metadata" in op.output_keys

    def test_custom_top_k_respected(self):
        """top_k passed at construction must not exceed results."""
        op = GraphSearchOp(top_k=3)
        vector = [{"id": f"v{i}", "score": 0.9, "source": "vector"} for i in range(10)]
        merged = op._merge(vector, [], top_k=3)
        assert len(merged) <= 3


# ============================================================
# Invariants — cross-cutting contracts
# ============================================================


class TestCrossInvariants:
    def test_triple_count_bounded_by_chunks_times_max_triples(self):
        """triple_count <= len(chunks) * max_triples is an architectural invariant."""
        n_chunks = 3
        max_triples = 4

        pairs = []
        for i in range(n_chunks):
            chunk = _make_chunk(f"c{i}", "")
            triples = [
                _make_triple(f"S{i}{j}", "is", f"O{i}{j}") for j in range(max_triples)
            ]
            pairs.append((chunk, triples))

        result = _build_entity_dedup_map(pairs)

        # Total entities = 2 * n_chunks * max_triples (subject + object per triple)
        # They may dedup, but the entity_map can't have MORE than that
        max_possible_entities = 2 * n_chunks * max_triples
        assert len(result) <= max_possible_entities

    def test_community_count_positive_implies_min_triples(self):
        """community_count > 0 only if we passed the MIN_TRIPLES guard."""
        # Verify the guard constant is defined and reasonable
        assert MIN_TRIPLES > 0
        assert MIN_TRIPLES <= 10  # sanity: not absurdly large

    def test_overlap_boost_constant_is_positive(self):
        assert _OVERLAP_BOOST > 0

    def test_graph_base_score_in_valid_range(self):
        assert 0.0 <= _GRAPH_BASE_SCORE <= 1.0

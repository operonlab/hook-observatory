"""cross_vault_qa — dispatcher behaviour tests.

Mock boundaries:
- memvault.services.memory_block_service.qdrant_search (external module, allowed)
- docvault.qa_service.QAService.ask (external module, allowed)
- src.shared.embedding.get_embedding (external pipeline, allowed)
- src.modules.assistant.cross_vault_service.classify_intent (we want to drive
  routing decisions deterministically — strict mocking of the boundary inside
  this module is still acceptable because classify_intent is an external
  dependency from cross_vault_qa's perspective)

Internal wiring (citation construction, answer fallback, asyncio.gather)
runs real.

六鐵律 disclosure: main-thread author. See test_schemas.py header.
"""

from __future__ import annotations

import asyncio
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.assistant import cross_vault_service as cv
from src.modules.assistant.schemas import AssistantQARequest, AssistantQAResponse


# ── Fakes ──────────────────────────────────────────────────────────────


def _fake_block(block_id: str, content: str, score: float = 0.7) -> Any:
    """A duck-typed memvault SemanticSearchResult-ish object."""
    b = MagicMock()
    b.id = block_id
    b.content = content
    b.block_type = "fact"
    b.final_score = score
    return b


def _fake_dv_response(answer: str, citations: list[Any] | None = None, log_id: str | None = "log-1") -> Any:
    r = MagicMock()
    r.answer = answer
    r.citations = citations or []
    r.qa_log_id = log_id
    return r


def _fake_dv_citation(document_id: str, section: str, chunk_id: str = "c1") -> Any:
    c = MagicMock()
    c.document_id = document_id
    c.chunk_id = chunk_id
    c.section = section
    c.quote = None
    return c


@pytest.fixture
def fake_db():
    return MagicMock()


@pytest.fixture(autouse=True)
def _patch_external(monkeypatch):
    """Default mocks: embedding works, both vaults return empty.

    Individual tests override these by re-assigning attributes on the mocks.
    """
    mock_embed = AsyncMock(return_value=[0.0] * 1024)

    fake_memvault_module = types.ModuleType("src.modules.memvault.services")
    fake_memvault_module.memory_block_service = MagicMock()
    fake_memvault_module.memory_block_service.qdrant_search = AsyncMock(
        return_value=([], MagicMock())
    )

    fake_embed_module = types.ModuleType("src.shared.embedding")
    fake_embed_module.get_embedding = mock_embed

    class FakeQAService:
        ask = AsyncMock(return_value=_fake_dv_response("default doc answer", []))

    fake_dv_module = types.ModuleType("src.modules.docvault.qa_service")
    fake_dv_module.QAService = FakeQAService
    fake_dv_module._FakeQAService = FakeQAService

    fake_dv_schemas = types.ModuleType("src.modules.docvault.schemas")

    class FakeQARequest:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    fake_dv_schemas.QARequest = FakeQARequest

    monkeypatch.setitem(__import__("sys").modules, "src.modules.memvault.services", fake_memvault_module)
    monkeypatch.setitem(__import__("sys").modules, "src.shared.embedding", fake_embed_module)
    monkeypatch.setitem(__import__("sys").modules, "src.modules.docvault.qa_service", fake_dv_module)
    monkeypatch.setitem(__import__("sys").modules, "src.modules.docvault.schemas", fake_dv_schemas)

    yield {
        "memvault": fake_memvault_module,
        "docvault_service": fake_dv_module,
        "embedding": fake_embed_module,
    }


# ── Routing semantics ──────────────────────────────────────────────────


def test_routing_memory_calls_only_memvault(fake_db, _patch_external):
    """Killer: implementation that runs gather() regardless of intent fails here."""
    _patch_external["memvault"].memory_block_service.qdrant_search = AsyncMock(
        return_value=(
            [_fake_block("b1", "I prefer worktree isolation"), _fake_block("b2", "Avoid --no-verify")],
            MagicMock(),
        ),
    )
    docvault_ask = _patch_external["docvault_service"]._FakeQAService.ask
    docvault_ask.reset_mock()

    req = AssistantQARequest(question="我之前說過什麼？", routing="memory")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))

    assert isinstance(result, AssistantQAResponse)
    assert result.routing_decision == "memory"
    assert result.routing_model == "user-specified"
    assert result.memvault_hits == 2
    assert result.docvault_hits == 0
    assert docvault_ask.call_count == 0, "memory routing must not invoke docvault"
    assert len(result.citations) == 2
    assert all(c.source == "memvault" for c in result.citations)


def test_routing_doc_calls_only_docvault(fake_db, _patch_external):
    """Killer: same as above, opposite direction."""
    memvault_search = _patch_external["memvault"].memory_block_service.qdrant_search
    memvault_search.reset_mock()
    _patch_external["docvault_service"]._FakeQAService.ask = AsyncMock(
        return_value=_fake_dv_response(
            "memvault 有三條軌道",
            citations=[_fake_dv_citation("doc1", "section A")],
        )
    )

    req = AssistantQARequest(question="memvault 怎麼運作", routing="doc")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))

    assert result.routing_decision == "doc"
    assert result.memvault_hits == 0
    assert result.docvault_hits == 1
    assert memvault_search.call_count == 0
    assert result.answer == "memvault 有三條軌道"
    assert result.citations[0].source == "docvault"
    assert result.citations[0].document_id == "doc1"


def test_routing_mixed_calls_both(fake_db, _patch_external):
    _patch_external["memvault"].memory_block_service.qdrant_search = AsyncMock(
        return_value=(
            [_fake_block("b1", "memory content")],
            MagicMock(),
        ),
    )
    _patch_external["docvault_service"]._FakeQAService.ask = AsyncMock(
        return_value=_fake_dv_response(
            "doc answer",
            citations=[_fake_dv_citation("doc1", "section A"), _fake_dv_citation("doc2", "section B")],
        )
    )

    req = AssistantQARequest(question="比一比", routing="mixed")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))

    assert result.routing_decision == "mixed"
    assert result.memvault_hits == 1
    assert result.docvault_hits == 2
    assert result.answer == "doc answer"
    # memvault citations come first per commit contract
    assert result.citations[0].source == "memvault"
    assert result.citations[1].source == "docvault"
    assert result.citations[2].source == "docvault"


def test_routing_auto_uses_classifier(fake_db, monkeypatch, _patch_external):
    """auto → classify_intent decides; we drive it to 'doc'."""
    monkeypatch.setattr(
        cv,
        "classify_intent",
        AsyncMock(return_value={"intent": "doc", "model": "fake-mdl", "raw": "doc", "fallback": False}),
    )
    docvault_ask = _patch_external["docvault_service"]._FakeQAService.ask = AsyncMock(
        return_value=_fake_dv_response("doc answer", [_fake_dv_citation("doc1", "s")])
    )
    memvault_search = _patch_external["memvault"].memory_block_service.qdrant_search
    memvault_search.reset_mock()

    req = AssistantQARequest(question="x", routing="auto")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))

    assert result.routing_decision == "doc"
    assert result.routing_model == "fake-mdl"
    assert result.routing_fallback is False
    assert memvault_search.call_count == 0
    assert docvault_ask.call_count == 1


def test_routing_auto_classifier_fallback_propagates(fake_db, monkeypatch, _patch_external):
    """When classifier reports fallback=True, response must surface it."""
    monkeypatch.setattr(
        cv,
        "classify_intent",
        AsyncMock(return_value={"intent": "mixed", "model": "fake", "raw": "", "fallback": True}),
    )
    req = AssistantQARequest(question="x", routing="auto")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))
    assert result.routing_fallback is True


# ── Degraded paths ─────────────────────────────────────────────────────


def test_memvault_raises_does_not_crash(fake_db, _patch_external):
    _patch_external["memvault"].memory_block_service.qdrant_search = AsyncMock(
        side_effect=RuntimeError("qdrant down")
    )
    _patch_external["docvault_service"]._FakeQAService.ask = AsyncMock(
        return_value=_fake_dv_response("doc answer", [_fake_dv_citation("doc1", "s")])
    )

    req = AssistantQARequest(question="x", routing="mixed")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))
    assert result.memvault_hits == 0
    assert result.docvault_hits == 1
    assert result.answer == "doc answer"  # docvault still produced the answer


def test_docvault_raises_falls_back_to_memvault_synth(fake_db, _patch_external):
    _patch_external["memvault"].memory_block_service.qdrant_search = AsyncMock(
        return_value=([_fake_block("b1", "synthetic content here")], MagicMock()),
    )
    _patch_external["docvault_service"]._FakeQAService.ask = AsyncMock(
        side_effect=RuntimeError("docvault crashed")
    )
    req = AssistantQARequest(question="x", routing="mixed")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))
    assert result.docvault_hits == 0
    assert result.memvault_hits == 1
    assert "synthetic content here" in result.answer


def test_both_empty_returns_polite_no_memory_message(fake_db, _patch_external):
    """Killer: if implementation silently returns "" on both-empty,
    downstream UIs would show a blank chat bubble.
    """
    req = AssistantQARequest(question="x", routing="memory")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))
    assert result.answer.strip() != ""
    assert result.memvault_hits == 0


# ── Citation construction invariants ───────────────────────────────────


def test_memvault_citations_carry_block_content_preview(fake_db, _patch_external):
    long_content = "a" * 1500
    _patch_external["memvault"].memory_block_service.qdrant_search = AsyncMock(
        return_value=([_fake_block("b1", long_content)], MagicMock()),
    )
    req = AssistantQARequest(question="x", routing="memory")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))
    cit = result.citations[0]
    # Implementation should cap preview to keep response payload modest
    assert cit.block_content is not None
    assert len(cit.block_content) <= 600


def test_docvault_space_override_passed_through(fake_db, _patch_external):
    docvault_ask = _patch_external["docvault_service"]._FakeQAService.ask = AsyncMock(
        return_value=_fake_dv_response("answer", [])
    )
    req = AssistantQARequest(
        question="x", routing="doc", docvault_space="obsidian-blog"
    )
    asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))
    call_kwargs = docvault_ask.call_args.kwargs
    assert call_kwargs.get("space_id") == "obsidian-blog"


def test_docvault_space_defaults_to_caller_space(fake_db, _patch_external):
    docvault_ask = _patch_external["docvault_service"]._FakeQAService.ask = AsyncMock(
        return_value=_fake_dv_response("answer", [])
    )
    req = AssistantQARequest(question="x", routing="doc")  # no override
    asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="user-42"))
    call_kwargs = docvault_ask.call_args.kwargs
    assert call_kwargs.get("space_id") == "user-42"

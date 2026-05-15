"""cross_vault_qa — dispatcher behaviour tests.

Mock boundaries (六鐵律 #5: external I/O only):
- memvault.services.memory_block_service.qdrant_search (cross-module entry)
- src.shared.embedding.get_embedding (cross-module entry)
- httpx.AsyncClient — cross_vault_service self-calls POST /api/docvault/qa
  over loopback, so the HTTP client is the boundary (docvault has two QA
  paths and the inline one in routes.py is the only one wired to the
  synthesizer — we self-call to stay on the supported path).

Internal wiring (citation construction, asyncio.gather, answer fallback)
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
    """Mimic memvault SemanticSearchResult(block, score) shape."""
    inner = MagicMock()
    inner.id = block_id
    inner.content = content
    inner.block_type = "fact"
    item = MagicMock()
    item.block = inner
    item.score = score
    return item


def _fake_dv_http_response(
    answer: str,
    citations: list[dict] | None = None,
    log_id: str | None = "log-1",
    status_code: int = 200,
) -> Any:
    """Mimic httpx.Response for the docvault /qa self-call."""
    r = MagicMock()
    r.status_code = status_code
    r.text = answer if status_code >= 400 else ""
    r.json.return_value = {
        "answer": answer,
        "citations": citations or [],
        "qa_log_id": log_id,
    }
    return r


@pytest.fixture
def fake_db():
    return MagicMock()


class _StubAsyncClient:
    """Stub for httpx.AsyncClient — drives the docvault HTTP self-call."""

    def __init__(self, post_response: Any | None = None, raise_on_post: Exception | None = None):
        self._post_response = post_response
        self._raise_on_post = raise_on_post
        self.post_calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def post(self, url: str, **kw):
        self.post_calls.append({"url": url, **kw})
        if self._raise_on_post:
            raise self._raise_on_post
        return self._post_response


@pytest.fixture(autouse=True)
def _patch_external(monkeypatch):
    """Default mocks: embedding works, memvault returns empty, docvault HTTP
    returns a default answer. Individual tests override fields on the
    returned dict to drive behaviour.
    """
    mock_embed = AsyncMock(return_value=[0.0] * 1024)

    fake_memvault_module = types.ModuleType("src.modules.memvault.services")
    fake_memvault_module.memory_block_service = MagicMock()
    fake_memvault_module.memory_block_service.qdrant_search = AsyncMock(
        return_value=([], MagicMock())
    )

    fake_embed_module = types.ModuleType("src.shared.embedding")
    fake_embed_module.get_embedding = mock_embed

    monkeypatch.setitem(
        __import__("sys").modules,
        "src.modules.memvault.services",
        fake_memvault_module,
    )
    monkeypatch.setitem(__import__("sys").modules, "src.shared.embedding", fake_embed_module)

    # Default httpx stub: 200 with empty answer + no citations.
    stub = _StubAsyncClient(post_response=_fake_dv_http_response("", []))

    def _factory(*a, **kw):
        return stub

    monkeypatch.setattr(cv.__name__ + ".httpx", types.SimpleNamespace(AsyncClient=_factory))

    yield {
        "memvault": fake_memvault_module,
        "embedding": fake_embed_module,
        "docvault_stub": stub,
        "set_docvault_response": lambda resp: setattr(stub, "_post_response", resp),
        "set_docvault_raise": lambda exc: setattr(stub, "_raise_on_post", exc),
    }


def _override_docvault_via_monkeypatch(monkeypatch, stub: _StubAsyncClient):
    """Re-install the (mutated) stub. Needed when a test wants a fresh stub."""
    monkeypatch.setattr(
        cv.__name__ + ".httpx", types.SimpleNamespace(AsyncClient=lambda *a, **kw: stub)
    )


# ── Routing semantics ──────────────────────────────────────────────────


def test_routing_memory_calls_only_memvault(fake_db, _patch_external):
    """Killer: implementation that always gathers both vaults fails here."""
    _patch_external["memvault"].memory_block_service.qdrant_search = AsyncMock(
        return_value=(
            [
                _fake_block("b1", "I prefer worktree isolation"),
                _fake_block("b2", "Avoid --no-verify"),
            ],
            MagicMock(),
        ),
    )

    req = AssistantQARequest(question="我之前說過什麼？", routing="memory")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))

    assert isinstance(result, AssistantQAResponse)
    assert result.routing_decision == "memory"
    assert result.routing_model == "user-specified"
    assert result.memvault_hits == 2
    assert result.docvault_hits == 0
    assert len(_patch_external["docvault_stub"].post_calls) == 0, (
        "memory routing must not invoke docvault"
    )
    assert len(result.citations) == 2
    assert all(c.source == "memvault" for c in result.citations)


def test_routing_doc_calls_only_docvault(fake_db, _patch_external):
    """Killer: same as above, opposite direction."""
    memvault_search = _patch_external["memvault"].memory_block_service.qdrant_search
    memvault_search.reset_mock()
    _patch_external["set_docvault_response"](
        _fake_dv_http_response(
            "memvault 有三條軌道",
            citations=[{"document_id": "doc1", "section": "section A", "chunk_id": "c1"}],
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
        return_value=([_fake_block("b1", "memory content")], MagicMock()),
    )
    _patch_external["set_docvault_response"](
        _fake_dv_http_response(
            "doc answer",
            citations=[
                {"document_id": "doc1", "section": "section A", "chunk_id": "c1"},
                {"document_id": "doc2", "section": "section B", "chunk_id": "c2"},
            ],
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
        AsyncMock(
            return_value={"intent": "doc", "model": "fake-mdl", "raw": "doc", "fallback": False}
        ),
    )
    _patch_external["set_docvault_response"](
        _fake_dv_http_response("doc answer", citations=[{"document_id": "doc1"}])
    )
    memvault_search = _patch_external["memvault"].memory_block_service.qdrant_search
    memvault_search.reset_mock()

    req = AssistantQARequest(question="x", routing="auto")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))

    assert result.routing_decision == "doc"
    assert result.routing_model == "fake-mdl"
    assert result.routing_fallback is False
    assert memvault_search.call_count == 0
    assert len(_patch_external["docvault_stub"].post_calls) == 1


def test_routing_auto_classifier_fallback_propagates(fake_db, monkeypatch, _patch_external):
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
    _patch_external["set_docvault_response"](
        _fake_dv_http_response("doc answer", citations=[{"document_id": "doc1"}])
    )

    req = AssistantQARequest(question="x", routing="mixed")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))
    assert result.memvault_hits == 0
    assert result.docvault_hits == 1
    assert result.answer == "doc answer"


def test_docvault_raises_falls_back_to_memvault_synth(fake_db, _patch_external):
    _patch_external["memvault"].memory_block_service.qdrant_search = AsyncMock(
        return_value=([_fake_block("b1", "synthetic content here")], MagicMock()),
    )
    _patch_external["set_docvault_raise"](RuntimeError("docvault crashed"))
    req = AssistantQARequest(question="x", routing="mixed")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))
    assert result.docvault_hits == 0
    assert result.memvault_hits == 1
    assert "synthetic content here" in result.answer


def test_docvault_http_error_falls_back_to_memvault_synth(fake_db, _patch_external):
    """Killer: HTTP 5xx should be treated as failure, not propagated."""
    _patch_external["memvault"].memory_block_service.qdrant_search = AsyncMock(
        return_value=([_fake_block("b1", "memvault content xyz")], MagicMock()),
    )
    _patch_external["set_docvault_response"](
        _fake_dv_http_response("server error", status_code=500)
    )
    req = AssistantQARequest(question="x", routing="mixed")
    result = asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))
    assert result.docvault_hits == 0
    assert "memvault content xyz" in result.answer


def test_both_empty_returns_polite_no_memory_message(fake_db, _patch_external):
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
    assert cit.block_content is not None
    assert len(cit.block_content) <= 600
    assert cit.block_id == "b1"


def test_docvault_space_override_passed_through(fake_db, _patch_external):
    _patch_external["set_docvault_response"](_fake_dv_http_response("answer", []))
    req = AssistantQARequest(question="x", routing="doc", docvault_space="obsidian-blog")
    asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))
    call = _patch_external["docvault_stub"].post_calls[0]
    assert call["params"]["space_id"] == "obsidian-blog"


def test_docvault_space_defaults_to_caller_space(fake_db, _patch_external):
    _patch_external["set_docvault_response"](_fake_dv_http_response("answer", []))
    req = AssistantQARequest(question="x", routing="doc")
    asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="user-42"))
    call = _patch_external["docvault_stub"].post_calls[0]
    assert call["params"]["space_id"] == "user-42"


def test_docvault_tags_passed_through(fake_db, _patch_external):
    """Killer: tags filter must reach the docvault HTTP body."""
    _patch_external["set_docvault_response"](_fake_dv_http_response("answer", []))
    req = AssistantQARequest(question="x", routing="doc", docvault_tags=["posts", "tech"])
    asyncio.run(cv.cross_vault_qa(fake_db, req, space_id="default"))
    call = _patch_external["docvault_stub"].post_calls[0]
    assert call["json"]["tags"] == ["posts", "tech"]

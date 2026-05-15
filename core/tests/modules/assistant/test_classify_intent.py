"""classify_intent — LLM call wrapper tests.

Mock boundary: httpx.AsyncClient (external HTTP — allowed by 六鐵律 #5).
Internal normalize_intent runs real.

六鐵律 disclosure: main-thread author (see test_schemas.py header for
context). Mutation-thinking enforced via killer tests per behaviour.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.modules.assistant.ops import query_router


def _ok_response(content: str) -> Any:
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"choices": [{"message": {"content": content}}]}
    return m


def _http_error(status_code: int, body: str = "rate limit") -> Any:
    m = MagicMock()
    m.status_code = status_code
    m.text = body
    return m


class _FakeClient:
    """Stub for httpx.AsyncClient — feeds canned responses to .post and .get."""

    def __init__(
        self,
        post_responses: list[Any],
        *,
        get_response: Any | None = None,
        raise_on_post: Exception | None = None,
        raise_on_get: Exception | None = None,
    ):
        self.post_responses = list(post_responses)
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self._get_response = get_response or _ok_response_models([])
        self._raise_post = raise_on_post
        self._raise_get = raise_on_get

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def post(self, url: str, **kw):
        self.post_calls.append({"url": url, **kw})
        if self._raise_post:
            raise self._raise_post
        if not self.post_responses:
            raise AssertionError("Unexpected extra POST call")
        return self.post_responses.pop(0)

    async def get(self, url: str, **kw):
        self.get_calls.append({"url": url, **kw})
        if self._raise_get:
            raise self._raise_get
        return self._get_response


def _ok_response_models(model_ids: list[str]) -> Any:
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {"data": [{"id": i} for i in model_ids]}
    return m


@pytest.fixture(autouse=True)
def _reset_model_cache():
    """Reset the resolve_cheap_model cache so test order can't leak state."""
    query_router._cached_model = None
    query_router._cached_model_ts = 0.0
    yield
    query_router._cached_model = None
    query_router._cached_model_ts = 0.0


def _install_fake_client(monkeypatch, fake: _FakeClient):
    monkeypatch.setattr(
        "src.modules.assistant.ops.query_router.httpx.AsyncClient",
        lambda *a, **kw: fake,
    )


# ── Happy path ─────────────────────────────────────────────────────────


def test_success_returns_intent_from_llm(monkeypatch):
    fake = _FakeClient(
        post_responses=[_ok_response("memory")],
        get_response=_ok_response_models(["deepseek-v3"]),
    )
    _install_fake_client(monkeypatch, fake)
    result = asyncio.run(query_router.classify_intent("我之前說過什麼？"))
    assert result["intent"] == "memory"
    assert result["fallback"] is False
    assert result["model"] == "deepseek-v3"


def test_success_doc_intent(monkeypatch):
    fake = _FakeClient(
        post_responses=[_ok_response("doc")],
        get_response=_ok_response_models(["deepseek-v3"]),
    )
    _install_fake_client(monkeypatch, fake)
    result = asyncio.run(query_router.classify_intent("memvault 怎麼運作？"))
    assert result["intent"] == "doc"


# ── Killer: failure chain walks to next model ──────────────────────────


def test_first_model_429_falls_to_second(monkeypatch):
    """Mutation killer: if implementation tries only one model and gives up,
    this test will fail because intent will be 'mixed' (fallback) instead of
    'doc' (the second model's actual answer).
    """
    fake = _FakeClient(
        post_responses=[
            _http_error(429, "Rate limit exceeded"),
            _ok_response("doc"),
        ],
        get_response=_ok_response_models(
            ["deepseek-v3", "qwen3.5-flash", "glm-4.5-air"]
        ),
    )
    _install_fake_client(monkeypatch, fake)
    result = asyncio.run(query_router.classify_intent("blog 上 X 怎麼寫？"))
    assert result["intent"] == "doc"
    assert result["fallback"] is False
    assert len(fake.post_calls) == 2


def test_all_models_fail_returns_mixed_fallback(monkeypatch):
    fake = _FakeClient(
        post_responses=[
            _http_error(429, "rate limit"),
            _http_error(500, "internal"),
            _http_error(429, "rate limit"),
            _http_error(429, "rate limit"),
            _http_error(429, "rate limit"),
        ],
        get_response=_ok_response_models(query_router._CHEAP_MODELS),
    )
    _install_fake_client(monkeypatch, fake)
    result = asyncio.run(query_router.classify_intent("anything"))
    assert result["intent"] == "mixed"
    assert result["fallback"] is True
    assert "error" in result
    assert len(fake.post_calls) == len(query_router._CHEAP_MODELS)


def test_httpx_raises_falls_back_to_mixed(monkeypatch):
    fake = _FakeClient(
        post_responses=[],
        raise_on_post=httpx.ConnectError("boom"),
        get_response=_ok_response_models(["deepseek-v3"]),
    )
    _install_fake_client(monkeypatch, fake)
    result = asyncio.run(query_router.classify_intent("anything"))
    assert result["intent"] == "mixed"
    assert result["fallback"] is True


# ── Killer: empty / whitespace short-circuits before LLM call ──────────


def test_empty_query_skips_llm_call(monkeypatch):
    """Mutation killer: implementation that calls LLM before checking
    empty input would trigger the FakeClient's 'no responses queued'
    assertion, surfacing as a test failure.
    """
    fake = _FakeClient(post_responses=[], get_response=_ok_response_models([]))
    _install_fake_client(monkeypatch, fake)
    result = asyncio.run(query_router.classify_intent(""))
    assert result["intent"] == "mixed"
    assert result["fallback"] is True
    assert len(fake.post_calls) == 0, "empty query must not invoke LLM"


def test_whitespace_only_query_skips_llm_call(monkeypatch):
    fake = _FakeClient(post_responses=[], get_response=_ok_response_models([]))
    _install_fake_client(monkeypatch, fake)
    result = asyncio.run(query_router.classify_intent("   \n\t  "))
    assert result["intent"] == "mixed"
    assert result["fallback"] is True
    assert len(fake.post_calls) == 0


# ── Explicit model override skips resolve_cheap_model ──────────────────


def test_explicit_model_argument_used_verbatim(monkeypatch):
    fake = _FakeClient(
        post_responses=[_ok_response("doc")],
        get_response=_ok_response_models([]),  # /models would resolve to empty
    )
    _install_fake_client(monkeypatch, fake)
    result = asyncio.run(
        query_router.classify_intent("anything", model="custom-model-xyz")
    )
    assert result["model"] == "custom-model-xyz"
    # POST body should target the override
    assert fake.post_calls[0]["json"]["model"] == "custom-model-xyz"


# ── Return-dict shape invariant ────────────────────────────────────────


def test_return_shape_has_required_keys(monkeypatch):
    fake = _FakeClient(
        post_responses=[_ok_response("memory")],
        get_response=_ok_response_models(["deepseek-v3"]),
    )
    _install_fake_client(monkeypatch, fake)
    result = asyncio.run(query_router.classify_intent("x"))
    assert set(result.keys()) >= {"intent", "model", "raw", "fallback"}
    assert result["intent"] in ("memory", "doc", "mixed")
    assert isinstance(result["fallback"], bool)


# ── max_tokens budget is tight (we only need a one-word answer) ────────


def test_post_body_uses_low_max_tokens(monkeypatch):
    """Cost guard: classifier must not request more than a few output tokens.

    Mutation killer: if someone bumps max_tokens=4000 by accident, this
    test will catch the regression and force a code review.
    """
    fake = _FakeClient(
        post_responses=[_ok_response("memory")],
        get_response=_ok_response_models(["deepseek-v3"]),
    )
    _install_fake_client(monkeypatch, fake)
    asyncio.run(query_router.classify_intent("x"))
    sent = fake.post_calls[0]["json"]
    assert sent["max_tokens"] <= 32, f"classifier budget should stay tiny, got {sent['max_tokens']}"
    assert sent["temperature"] == 0

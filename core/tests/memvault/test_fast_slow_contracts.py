"""Memvault fast/slow contracts — adversarial tests under 六鐵律.

Six Iron Rules applied here:
  1. Mutation thinking        — each test documents the mutation it kills
  2. Writer/tester separation — contracts derived from public schema/route/client shape
  3. Invariants over fixed I/O — precedence and fallback rules before examples
  4. Mock only external I/O   — HTTP/db edges stubbed; contract logic runs live
  5. Runtime regression       — route exercised through ASGI transport
  6. Tests are drafts         — each test explains its validation target
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

_CORE_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SDK_ROOT = _REPO_ROOT / "libs" / "sdk-client"

for candidate in (str(_CORE_ROOT), str(_SDK_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from sdk_client.memvault import MemvaultClient
from src.modules.memvault.query_runtime import build_injection_payload, choose_thinking_mode
from src.modules.memvault.schemas import (
    MemoryCard,
    MemoryEvidenceRef,
    MemoryQueryResponse,
    MemoryQueryStrategy,
)


class TestThinkingModePrecedence:
    """Invariant-first tests for fast/slow route selection."""

    def test_ui_auto_forces_slow(self):
        """Mutation target: removing UI precedence would return fast here."""
        assert choose_thinking_mode("build", "auto", "standard", "ui") == "slow"

    def test_agent_preempts_deep_budget(self):
        """Mutation target: moving deep-budget before agent precedence flips to slow."""
        assert choose_thinking_mode("build", "auto", "deep", "agent") == "fast"

    def test_explicit_mode_beats_auto_heuristics(self):
        """Mutation target: ignoring explicit thinking_mode would make this slow."""
        assert choose_thinking_mode("reflect", "fast", "deep", "human") == "fast"


class TestInjectionPayloadFallbacks:
    """Contract tests for agent-facing payload assembly."""

    def test_inject_uses_fast_cards_before_working_cards(self):
        """Mutation target: swapping fallback order would lose preference memory."""
        response = MemoryQueryResponse(
            query="architectural preference",
            strategy=MemoryQueryStrategy(
                task_mode="build",
                thinking_mode_requested="auto",
                thinking_mode_used="fast",
                load_budget="light",
                consumer="agent",
            ),
            fast_cards=[
                MemoryCard(
                    id="fast-1",
                    title="偏好 / architecture",
                    summary="偏好漸進式重構而非全面重寫",
                    why_relevant="命中工作原則",
                    use_now="延續這個原則處理目前變更。",
                    layer="fast",
                    source_type="attitude",
                    confidence=0.95,
                    evidence_refs=[
                        MemoryEvidenceRef(
                            kind="attitude",
                            ref_id="att-1",
                            title="architecture",
                            snippet="偏好漸進式重構而非全面重寫",
                        )
                    ],
                )
            ],
            working_cards=[
                MemoryCard(
                    id="working-1",
                    title="working note",
                    summary="暫存工作上下文",
                    why_relevant="暫時性上下文",
                    use_now="先讀這張卡。",
                    layer="working",
                    source_type="block",
                    confidence=0.6,
                    evidence_refs=[],
                )
            ],
            deep_cards=[],
            highlights=[],
        )
        payload = build_injection_payload(response)
        assert "偏好漸進式重構而非全面重寫" in payload.system_prompt_memory
        assert payload.working_context == ["暫存工作上下文"]
        assert payload.decision_bias == ["偏好漸進式重構而非全面重寫"]

    def test_inject_falls_back_to_working_cards_when_fast_missing(self):
        """Mutation target: empty fast memory must not produce empty prompt payload."""
        response = MemoryQueryResponse(
            query="session status",
            strategy=MemoryQueryStrategy(
                task_mode="build",
                thinking_mode_requested="auto",
                thinking_mode_used="fast",
                load_budget="light",
                consumer="agent",
            ),
            fast_cards=[],
            working_cards=[
                MemoryCard(
                    id="working-1",
                    title="working note",
                    summary="目前正在重構 memvault fast/slow query runtime",
                    why_relevant="目前任務上下文",
                    use_now="把這段上下文注入提示詞。",
                    layer="working",
                    source_type="block",
                    confidence=0.7,
                    evidence_refs=[],
                )
            ],
            deep_cards=[],
            highlights=[],
        )
        payload = build_injection_payload(response)
        assert "目前正在重構 memvault fast/slow query runtime" in payload.system_prompt_memory
        assert payload.cards[0].layer == "working"


class TestSdkWireContracts:
    """Mock only external I/O: assert exact path/body to Core API."""

    def test_sdk_inspect_posts_to_inspect_endpoint(self, monkeypatch):
        """Mutation target: /inspect accidentally regresses to /query."""
        client = MemvaultClient(base_url="http://test")
        captured: dict = {}

        def fake_post(path: str, body: dict | None = None, params: dict | None = None, timeout=None):
            captured["path"] = path
            captured["body"] = body
            return {"ok": True}

        monkeypatch.setattr(client, "_post", fake_post)
        client.inspect("cache policy", task_mode="reflect", load_budget="deep", top_k=9)

        assert captured["path"] == "/inspect"
        assert captured["body"] == {
            "q": "cache policy",
            "task_mode": "reflect",
            "thinking_mode": "slow",
            "load_budget": "deep",
            "consumer": "human",
            "top_k": 9,
        }

    def test_sdk_inject_posts_agent_consumer(self, monkeypatch):
        """Mutation target: inject accidentally stops marking consumer=agent."""
        client = MemvaultClient(base_url="http://test")
        captured: dict = {}

        def fake_post(path: str, body: dict | None = None, params: dict | None = None, timeout=None):
            captured["path"] = path
            captured["body"] = body
            return {"ok": True}

        monkeypatch.setattr(client, "_post", fake_post)
        client.inject("style preference", task_mode="build")

        assert captured["path"] == "/inject"
        assert captured["body"]["consumer"] == "agent"
        assert captured["body"]["load_budget"] == "light"


class TestRouteContracts:
    """Runtime regression via ASGI transport — route behavior, not helper calls."""

    @pytest_asyncio.fixture
    async def inspect_client(self, monkeypatch):
        import src.modules.auth.permissions as auth_permissions
        import src.shared.deps as shared_deps

        monkeypatch.setattr(shared_deps, "get_current_user", lambda request: {"role": "admin"})
        monkeypatch.setattr(auth_permissions, "has_permission", lambda role, permission: True)

        import src.modules.memvault.routes as routes_module

        routes_module = importlib.reload(routes_module)
        app = FastAPI()
        app.include_router(routes_module.router, prefix="/api/memvault")

        async def override_db():
            yield AsyncMock()

        app.dependency_overrides[shared_deps.get_db] = override_db

        captured: dict = {}

        async def fake_run_memory_query(db, space_id, request):
            captured["request"] = request
            return MemoryQueryResponse(
                query=request.q,
                strategy=MemoryQueryStrategy(
                    task_mode=request.task_mode,
                    thinking_mode_requested=request.thinking_mode,
                    thinking_mode_used="slow",
                    load_budget=request.load_budget,
                    consumer=request.consumer,
                ),
                deep_cards=[],
            )

        def fake_build_inspect(response):
            return {
                "query": response.query,
                "strategy": response.strategy.model_dump(),
                "cards": [],
                "raw_sections": {},
                "metadata": None,
            }

        monkeypatch.setattr(routes_module, "run_memory_query", fake_run_memory_query)
        monkeypatch.setattr(routes_module, "build_inspect_payload", fake_build_inspect)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, captured

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_inspect_route_forces_slow_human_contract(self, inspect_client):
        """Mutation target: if /inspect stops rewriting the request, this fails."""
        client, captured = inspect_client
        response = await client.post(
            "/api/memvault/inspect",
            params={"space_id": "default"},
            json={
                "q": "memory budget",
                "task_mode": "build",
                "thinking_mode": "fast",
                "load_budget": "light",
                "consumer": "ui",
                "top_k": 3,
            },
        )

        assert response.status_code == 200
        request = captured["request"]
        assert request.thinking_mode == "slow"
        assert request.consumer == "human"
        assert request.load_budget == "light"

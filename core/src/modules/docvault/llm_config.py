"""DocVault LLM configuration — PydanticAI model factory + shared deps."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any

import httpx
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

logger = logging.getLogger(__name__)

_LITELLM_BASE = "http://localhost:4000/v1"
_LITELLM_KEY = "sk-litellm-local-dev"

_MODEL_CANDIDATES = [
    # Order = runtime preference. Gemini is last because its Studio
    # monthly cap can run out mid-month and `resolve_model` only checks
    # /v1/models (which still lists the model after the cap is hit),
    # so the actual completion calls would 429 every time. Reorder lets
    # us prefer providers that have headroom for synth pipeline work.
    "deepseek-v3",
    "kimi-k2.5",
    "minimax-m2.7-hs",
    "qwen3.5-flash",
    "grok-4.1-fast",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash",
]

# ── Model resolution cache ──
_cached_model: str | None = None
_cached_model_ts: float = 0.0
_CACHE_TTL = 60.0


async def resolve_model(
    base_url: str = _LITELLM_BASE,
    api_key: str = _LITELLM_KEY,
    candidates: list[str] | None = None,
) -> str:
    """Pick first available model from candidates via LiteLLM /v1/models. Cached 60s."""
    global _cached_model, _cached_model_ts
    now = time.monotonic()
    if _cached_model and (now - _cached_model_ts) < _CACHE_TTL:
        return _cached_model

    cands = candidates or _MODEL_CANDIDATES
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            available = {m["id"] for m in resp.json().get("data", [])}
            for c in cands:
                if c in available:
                    _cached_model = c
                    _cached_model_ts = now
                    return c
    except Exception:
        logger.debug("resolve_model: failed to query LiteLLM /models, using default")

    _cached_model = cands[0]
    _cached_model_ts = now
    return _cached_model


def make_model(
    model_name: str,
    base_url: str = _LITELLM_BASE,
    api_key: str = _LITELLM_KEY,
) -> OpenAIChatModel:
    """Create a PydanticAI OpenAIChatModel pointing at LiteLLM proxy."""
    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    return OpenAIChatModel(model_name, provider=provider)


async def get_model() -> OpenAIChatModel:
    """Resolve best available model + create OpenAIChatModel in one call."""
    name = await resolve_model()
    return make_model(name)


# ── Prompt-cache routing ──
#
# OpenAI's prompt_cache_key parameter (and LiteLLM's pass-through for
# OpenAI-compatible upstreams) routes requests with the same key to the same
# backend, raising automatic prefix-cache hit rate. We hash the document set
# so multi-turn QA on the same document(s) routes consistently.
#
# Provider compatibility relies on LiteLLM's drop_params=true (configured at
# proxy level in ~/.config/litellm/config.yaml: litellm_settings.drop_params).
# That guarantees prompt_cache_key is silently stripped for upstreams that
# don't accept it (e.g. xAI/Grok, Gemini), so callers don't need per-request
# guarding.

_CACHE_KEY_PREFIX = "docvault"
_DEFAULT_CACHE_KEY = f"{_CACHE_KEY_PREFIX}-default"
_CACHE_KEY_SANITIZE = re.compile(r"[^A-Za-z0-9_-]")


def safe_cache_token(prefix: str, value: Any, *, max_len: int = 32) -> str:
    """Build a cache-key-safe token (alnum + dash/underscore) under length cap."""
    safe = _CACHE_KEY_SANITIZE.sub("-", str(value))[:max_len].strip("-")
    return f"{prefix}-{safe or 'default'}"


def cache_key_for_chunks(chunks: list[dict[str, Any]] | None) -> str:
    """Build a stable prompt_cache_key from chunk document IDs.

    Same set of documents → same key → same backend → higher prefix-cache hit.
    Defends against non-dict entries and non-string document_id values.
    """
    if not chunks:
        return _DEFAULT_CACHE_KEY
    doc_ids = sorted(
        {
            str(c.get("document_id", ""))
            for c in chunks
            if isinstance(c, dict) and c.get("document_id")
        }
    )
    if not doc_ids:
        return _DEFAULT_CACHE_KEY
    digest = hashlib.sha256(";".join(doc_ids).encode()).hexdigest()[:32]
    return f"{_CACHE_KEY_PREFIX}-{digest}"


def cache_settings(
    chunks: list[dict[str, Any]] | None = None,
    *,
    temperature: float = 0.2,
    cache_key: str | None = None,
) -> dict[str, Any]:
    """PydanticAI model_settings with prompt-caching hints.

    `cache_key` overrides `chunks`-derived key when provided.
    """
    return {
        "temperature": temperature,
        "openai_prompt_cache_key": cache_key or cache_key_for_chunks(chunks),
    }

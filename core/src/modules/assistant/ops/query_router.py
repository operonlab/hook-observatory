"""Cross-vault query router — classify intent so /api/assistant/qa knows
which retrieval surface to hit.

This is the *cross-vault* dispatcher. It is intentionally separate from
`docvault.ops.intent_router.IntentRouterOp`, which classifies intent
*within* docvault's pipeline (factual / mixed / meta → pipeline A/B/C).

The vaults at stake here:
- memvault: extracted blocks from past Claude Code conversations —
  personal context, evolving decisions, profile.
- docvault: user-authored or imported documents — blog posts, technical
  knowledge bases, factual lookup.

Calls the same LiteLLM proxy that docvault uses (port 4000), with a cheap
model and a tight token budget (intent classification only needs one word).
"""

from __future__ import annotations

import logging
import time
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

Intent = Literal["memory", "doc", "mixed"]
_INTENTS: tuple[Intent, ...] = ("memory", "doc", "mixed")

_LITELLM_BASE = "http://127.0.0.1:4000/v1"
_LITELLM_KEY = "sk-litellm-local-dev"

# Cheap candidates for intent classification. Order is the runtime fallback
# chain — if one returns 429 / 5xx we walk to the next. Gemini is last because
# its Studio monthly cap tends to bite during the month-end rush; the others
# typically have plenty of headroom for one-word classification calls.
_CHEAP_MODELS: tuple[str, ...] = (
    "deepseek-v3",
    "qwen3.5-flash",
    "glm-4.5-air",
    "kimi-k2.5",
    "gemini-3.1-flash-lite",
)

_cached_model: str | None = None
_cached_model_ts: float = 0.0
_MODEL_CACHE_TTL = 60.0

_SYSTEM_PROMPT = """You classify user queries for a dual-vault retrieval system.

Vaults at stake:
- memvault: extracted blocks from past conversations — personal context, prior decisions, evolving preferences.
- docvault: user-authored or imported documents — blog posts, technical specs, knowledge base. Ground-truth factual lookup.

Classify the query as EXACTLY ONE word:
- memory: asks about the user's past sessions, decisions, or personal preferences. ("我之前說過X", "我的選擇", "上次", "我記得")
- doc: asks about documented knowledge or factual lookup. ("memvault 怎麼運作", "blog 上 X 怎麼說", "什麼是 Y")
- mixed: needs both vaults to answer. ("我問過的事情，blog 上有寫嗎", "對比我的偏好和規範")

Output ONE word only: memory or doc or mixed.
""".strip()


async def _resolve_cheap_model(client: httpx.AsyncClient) -> str:
    """Resolve first available cheap model from LiteLLM /v1/models. 60s cache.

    If the proxy is unreachable, fall back to the first candidate.
    """
    global _cached_model, _cached_model_ts
    now = time.monotonic()
    if _cached_model and (now - _cached_model_ts) < _MODEL_CACHE_TTL:
        return _cached_model

    try:
        resp = await client.get(
            f"{_LITELLM_BASE}/models",
            headers={"Authorization": f"Bearer {_LITELLM_KEY}"},
            timeout=3,
        )
        available = {m["id"] for m in resp.json().get("data", [])}
        for c in _CHEAP_MODELS:
            if c in available:
                _cached_model = c
                _cached_model_ts = now
                return c
    except Exception:
        logger.debug("resolve_cheap_model: /models query failed, using default")

    _cached_model = _CHEAP_MODELS[0]
    _cached_model_ts = now
    return _cached_model


def normalize_intent(raw: str) -> Intent:
    """Map free-form LLM output to one of the three Intent literals.

    Order matters: 'mixed' is checked first so a response like 'mixed (both)'
    doesn't match 'memory' just because 'mem' appears later.
    Empty / unrecognized → 'mixed' (conservative fallback — fan-out catches more).
    """
    s = (raw or "").strip().lower()
    if not s:
        return "mixed"
    for candidate in ("mixed", "memory", "doc"):
        if candidate in s:
            return candidate
    return "mixed"


async def classify_intent(
    query: str,
    *,
    model: str | None = None,
    timeout: float = 10.0,
) -> dict[str, object]:
    """Classify a query's intent. Returns:
        {
          "intent": "memory" | "doc" | "mixed",
          "model": <model name actually used>,
          "raw": <raw LLM output>,
          "fallback": <bool — true if LLM call failed or output unrecognized>,
        }

    Never raises — LLM failure → fallback to "mixed" (safe over-fetch).
    """
    if not query or not query.strip():
        return {"intent": "mixed", "model": "", "raw": "", "fallback": True}

    candidates: tuple[str, ...] = (model,) if model else _CHEAP_MODELS
    last_error: str = ""
    async with httpx.AsyncClient(timeout=timeout) as client:
        for chosen in candidates:
            try:
                r = await client.post(
                    f"{_LITELLM_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {_LITELLM_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": chosen,
                        "messages": [
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": query.strip()},
                        ],
                        "temperature": 0,
                        "max_tokens": 8,
                    },
                )
                if r.status_code >= 400:
                    last_error = f"{chosen} HTTP {r.status_code}: {r.text[:120]}"
                    logger.info("classify_intent: %s rejected, trying next", chosen)
                    continue
                raw = r.json()["choices"][0]["message"]["content"]
                intent = normalize_intent(raw)
                fallback = intent == "mixed" and "mixed" not in (raw or "").lower()
                return {
                    "intent": intent,
                    "model": chosen,
                    "raw": (raw or "").strip()[:80],
                    "fallback": fallback,
                }
            except Exception as exc:
                last_error = f"{chosen} {type(exc).__name__}: {exc}"[:200]
                logger.info("classify_intent: %s threw, trying next: %s", chosen, exc)
                continue

    logger.warning("classify_intent: all candidates failed: %s", last_error)
    return {
        "intent": "mixed",
        "model": candidates[-1] if candidates else "",
        "raw": "",
        "fallback": True,
        "error": last_error,
    }

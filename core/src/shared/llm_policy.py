"""LiteLLM model policy — single source of truth for task → model preferences.

Why this module exists
----------------------
LiteLLM upstream periodically renames models without warning (grok-4-fast →
grok-4.1-fast, gemini-3.0-flash → gemini-3.1-flash-lite). Each rename
silently breaks every hardcoded ``model="..."`` reference in the codebase.

This module centralizes the per-task model preference list and resolves
the first currently-available model from LiteLLM at runtime. The companion
audit runner (``schedules/runners/ws_litellm_model_audit.py``) diffs the
codebase against LiteLLM each day and pushes a drift report when something
drops off the proxy.

Caller pattern
--------------
Replace::

    config = RLMConfig(model="grok-4-fast", ...)

with::

    from src.shared.llm_policy import resolve_model_for_task

    config = RLMConfig(model=resolve_model_for_task("kg_auto_evolve"), ...)

Pick the closest task tag from ``TASK_MODEL_PREFERENCES``. The function is
synchronous, caches for 60s, and falls back to the first candidate on
proxy failure (best-effort — let the actual LLM call surface the error).
"""

from __future__ import annotations

import logging
import os
import threading
import time

import httpx

logger = logging.getLogger(__name__)

_LITELLM_BASE = os.environ.get("LITELLM_PROXY_URL", "http://localhost:4000/v1")
_LITELLM_KEY = os.environ.get("LITELLM_LOCAL_KEY", "sk-litellm-local-dev")

# Task tag → ordered preference list. First model that LiteLLM actually serves
# is picked. Order is intentional: cheap+Chinese-strong models go first; the
# avoid-list (Gemini free-tier quota offenders) is deliberately excluded from
# hot-path tasks.
TASK_MODEL_PREFERENCES: dict[str, list[str]] = {
    # Tier 3 query router intent classification (memvault). Cheap + fast.
    "intent_classifier": [
        "deepseek-v3",
        "glm-4.5-air",
        "qwen3.5-flash",
        "gemini-2.5-flash",
    ],
    # KG triple extraction from Chinese text. Needs strong Chinese NLU + JSON.
    "kg_extraction": [
        "deepseek-v3",
        "qwen3.6-plus",
        "glm-5",
        "kimi-k2.5",
    ],
    # Conflict resolution between KG triples — reasoning-heavy.
    "conflict_resolve": [
        "deepseek-v3",
        "deepseek-r1",
        "qwen3.6-plus",
        "glm-5",
    ],
    # KG auto-evolve: link new triples to existing graph.
    "kg_auto_evolve": [
        "deepseek-v3",
        "qwen3.6-plus",
        "glm-5",
    ],
    # Query expansion / paraphrase — short generation.
    "query_expand": [
        "deepseek-v3",
        "glm-4.5-air",
        "qwen3.5-flash",
    ],
    # Digest / summary generation (paper module).
    "digest": [
        "deepseek-v3",
        "qwen3.6-plus",
        "kimi-k2.5",
        "glm-5",
    ],
    # Briefing curation / RSS synthesis (intelflow).
    "synthesis": [
        "deepseek-v3",
        "qwen3.6-plus",
        "glm-5",
    ],
    # Cited answer (docvault QA over Obsidian).
    "cited_answer": [
        "deepseek-v3",
        "grok-4.1-fast",
        "qwen3.5-flash",
        "glm-4.5-air",
    ],
    # Capture enrichment — fuzzy intake classification.
    "capture_enrich": [
        "deepseek-v3",
        "glm-4.5-air",
        "qwen3.5-flash",
    ],
    # Finance report summarization.
    "finance_report": [
        "deepseek-v3",
        "qwen3.6-plus",
        "glm-5",
    ],
}

# Per-task resolution cache. 60s TTL is enough to absorb LiteLLM restarts
# while staying responsive to config updates (e.g. operator adds a model).
_CACHE_TTL = 60.0
_resolution_cache: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


class NoModelAvailableError(RuntimeError):
    """No candidate for the task is available on LiteLLM."""


def fetch_available_models(
    base_url: str = _LITELLM_BASE,
    api_key: str = _LITELLM_KEY,
    timeout: float = 3.0,
) -> set[str]:
    """Query LiteLLM ``/v1/models`` and return the served model IDs.

    Empty set on any error — callers decide fallback behavior.
    """
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            return {m["id"] for m in resp.json().get("data", [])}
    except Exception as exc:
        logger.warning("fetch_available_models failed: %s", exc)
        return set()


def resolve_model_for_task(task: str) -> str:
    """Return the first available model for ``task``. Cached 60s per task.

    Behavior:
      - Cache hit (fresh): return cached value.
      - LiteLLM reachable + candidate present: return that candidate, cache it.
      - LiteLLM reachable but no candidate present: raise NoModelAvailableError.
      - LiteLLM unreachable + no cache: fall back to first candidate. The
        upstream call may still fail, but at least the policy module won't be
        the one to take the pipeline down.

    Args:
        task: One of the keys in ``TASK_MODEL_PREFERENCES``.

    Raises:
        NoModelAvailableError: Unknown task tag, or task has no candidate
            present on LiteLLM (proxy reachable but list empty for this task).
    """
    candidates = TASK_MODEL_PREFERENCES.get(task)
    if not candidates:
        raise NoModelAvailableError(f"Unknown task tag: {task}")

    now = time.monotonic()
    cached = _resolution_cache.get(task)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    with _lock:
        cached = _resolution_cache.get(task)
        if cached and (now - cached[1]) < _CACHE_TTL:
            return cached[0]

        available = fetch_available_models()
        if not available:
            fallback = candidates[0]
            logger.warning(
                "resolve_model_for_task(%s): LiteLLM unreachable, falling back to %s",
                task,
                fallback,
            )
            _resolution_cache[task] = (fallback, now)
            return fallback

        for c in candidates:
            if c in available:
                _resolution_cache[task] = (c, now)
                return c

        raise NoModelAvailableError(
            f"No candidate model for task {task!r} available on LiteLLM. "
            f"Wanted any of {candidates}, available: {sorted(available)}"
        )


def all_referenced_models() -> set[str]:
    """Flatten every candidate across every task. Used by the audit runner."""
    out: set[str] = set()
    for cands in TASK_MODEL_PREFERENCES.values():
        out.update(cands)
    return out


def clear_cache() -> None:
    """Drop the resolution cache. Useful for tests and the audit runner."""
    with _lock:
        _resolution_cache.clear()

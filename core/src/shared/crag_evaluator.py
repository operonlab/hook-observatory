"""Shared CRAG Evaluator — EvaluableResult protocol + module-agnostic evaluation.

Extracted from memvault/crag_evaluator.py (Phase 3) to support both memvault and docvault.
The module-specific evaluators can extend this with domain logic.

EvaluableResult protocol: any dataclass/dict with a list of scored items can be evaluated.

Layer A (rule-based, <5ms): result count, score distribution, coverage heuristics.
Layer B delegated to caller (cross-encoder reranking is module-specific).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class CRAGVerdict(StrEnum):
    CORRECT = "correct"
    AMBIGUOUS = "ambiguous"
    INCORRECT = "incorrect"


@dataclass
class CRAGEvaluation:
    """Result of CRAG evaluation."""

    verdict: CRAGVerdict
    confidence_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


# ======================== EvaluableResult Protocol ========================


@runtime_checkable
class EvaluableResult(Protocol):
    """Protocol for results that can be evaluated by CRAG.

    Implementors must provide a way to extract scored items.
    Both memvault's CascadeRecallResult and docvault's chunk lists
    can satisfy this protocol.
    """

    def get_scored_items(self) -> list[dict[str, Any]]:
        """Return list of dicts with at least 'score' and 'content' keys."""
        ...

    def get_layer_count(self) -> int:
        """Return number of distinct retrieval layers searched."""
        ...


# ======================== Adapter for plain lists ========================


class ListResultAdapter:
    """Wraps a plain list of dicts to satisfy EvaluableResult protocol."""

    def __init__(self, items: list[dict[str, Any]], score_key: str = "score") -> None:
        self._items = items
        self._score_key = score_key

    def get_scored_items(self) -> list[dict[str, Any]]:
        return self._items

    def get_layer_count(self) -> int:
        sources = {item.get("source", "default") for item in self._items}
        return max(len(sources), 1)


# ======================== Core Evaluation Functions ========================

# Thresholds (configurable via module-specific wrappers)
DEFAULT_CORRECT_AVG = 0.6
DEFAULT_CORRECT_MAX = 0.7
DEFAULT_AMBIGUOUS_AVG = 0.3

# Phase 2 — role-aware verdict (docvault). Roles that should not coexist as
# primary evidence: an invariant says "this is the rule", a fallback says
# "if PoC fails, do this instead". Top-K containing both, sourced from
# different documents, is a conflict the LLM should not silently average.
_AUTHORITATIVE_ROLES = {"invariant", "open-decision"}
_DEROGATIVE_ROLES = {"fallback"}


def _role_aware_check(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect role-level conflicts in top-5. Returns metadata dict.

    Only activates when at least one item carries `source_role`; otherwise
    returns an empty dict so modules without authority metadata (e.g.
    memvault) keep their existing verdict.
    """
    top5 = items[:5]
    has_role = any(it.get("source_role") for it in top5)
    if not has_role:
        return {}

    breakdown: dict[str, int] = {}
    role_to_docs: dict[str, set[str]] = {}
    for it in top5:
        role = it.get("source_role")
        if not role:
            continue
        breakdown[role] = breakdown.get(role, 0) + 1
        role_to_docs.setdefault(role, set()).add(it.get("document_id", ""))

    auth_present = _AUTHORITATIVE_ROLES & breakdown.keys()
    derog_present = _DEROGATIVE_ROLES & breakdown.keys()
    conflicting_roles: list[str] = []
    forced_ambiguous = False
    if auth_present and derog_present:
        # Same doc with both roles is normal (one doc has multiple sections).
        # Cross-doc co-occurrence is the conflict signal.
        auth_docs = {d for r in auth_present for d in role_to_docs.get(r, set())}
        derog_docs = {d for r in derog_present for d in role_to_docs.get(r, set())}
        if auth_docs - derog_docs and derog_docs - auth_docs:
            forced_ambiguous = True
            conflicting_roles = sorted(auth_present | derog_present)

    return {
        "evidence_breakdown": breakdown,
        "conflicting_roles": conflicting_roles,
        "forced_ambiguous": forced_ambiguous,
    }


def evaluate_evaluable(
    query: str,
    result: EvaluableResult,
    *,
    correct_avg: float = DEFAULT_CORRECT_AVG,
    correct_max: float = DEFAULT_CORRECT_MAX,
    ambiguous_avg: float = DEFAULT_AMBIGUOUS_AVG,
) -> CRAGEvaluation:
    """Evaluate any EvaluableResult using Layer A rule-based heuristics.

    Args:
        query: The original search query.
        result: Any object satisfying EvaluableResult protocol.
        correct_avg: Threshold for CORRECT verdict (avg score).
        correct_max: Threshold for CORRECT verdict (max score).
        ambiguous_avg: Threshold for AMBIGUOUS verdict (avg score).

    Returns:
        CRAGEvaluation with verdict, confidence, and metadata.
    """
    items = result.get_scored_items()
    layer_count = result.get_layer_count()

    if not items:
        return CRAGEvaluation(
            verdict=CRAGVerdict.INCORRECT,
            confidence_score=0.0,
            metadata={"reason": "empty_results", "result_count": 0},
        )

    scores = [item.get("score", 0.0) for item in items]
    avg_score = sum(scores) / len(scores) if scores else 0.0
    max_score = max(scores) if scores else 0.0

    # Coverage bonus: more layers = higher confidence
    coverage_bonus = min(layer_count / 4.0, 1.0) * 0.1

    # Density bonus: more results = higher confidence (up to cap)
    density_bonus = min(len(items) / 10.0, 1.0) * 0.1

    adjusted_avg = avg_score + coverage_bonus + density_bonus

    if adjusted_avg >= correct_avg and max_score >= correct_max:
        verdict = CRAGVerdict.CORRECT
    elif adjusted_avg >= ambiguous_avg:
        verdict = CRAGVerdict.AMBIGUOUS
    else:
        verdict = CRAGVerdict.INCORRECT

    # Role-aware override (P2): authoritative+derogative co-occurrence forces
    # AMBIGUOUS so downstream can switch to chain-of-evidence answering.
    role_meta = _role_aware_check(items)
    if role_meta.get("forced_ambiguous") and verdict == CRAGVerdict.CORRECT:
        verdict = CRAGVerdict.AMBIGUOUS

    confidence = round(min(adjusted_avg, 1.0), 3)

    metadata: dict[str, Any] = {
        "result_count": len(items),
        "avg_score": round(avg_score, 3),
        "max_score": round(max_score, 3),
        "layer_count": layer_count,
        "coverage_bonus": round(coverage_bonus, 3),
        "density_bonus": round(density_bonus, 3),
    }
    metadata.update(role_meta)

    return CRAGEvaluation(
        verdict=verdict,
        confidence_score=confidence,
        metadata=metadata,
    )


def evaluate_results(
    query: str,
    results: list[dict[str, Any]],
    score_key: str = "score",
    **kwargs: Any,
) -> CRAGEvaluation:
    """Convenience: evaluate a plain list of scored dicts.

    This is the most common entry point for docvault QA pipeline.
    """
    adapter = ListResultAdapter(results, score_key=score_key)
    return evaluate_evaluable(query, adapter, **kwargs)

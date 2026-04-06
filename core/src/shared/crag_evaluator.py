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

    confidence = round(min(adjusted_avg, 1.0), 3)

    return CRAGEvaluation(
        verdict=verdict,
        confidence_score=confidence,
        metadata={
            "result_count": len(items),
            "avg_score": round(avg_score, 3),
            "max_score": round(max_score, 3),
            "layer_count": layer_count,
            "coverage_bonus": round(coverage_bonus, 3),
            "density_bonus": round(density_bonus, 3),
        },
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

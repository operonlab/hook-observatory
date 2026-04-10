"""Memvault Reactive Operators — composable pipeline stages.

All operators implement the async Operator protocol from
core/src/shared/reactive.py (name, input_keys, output_keys, async __call__).

Base class: MemvaultOp (toggle + error isolation + timing).
"""

from ._base import MemvaultOp, PipelineMeta
from .dream_ops import (
    DreamConsolidateOp,
    DreamGatherSignalOp,
    DreamOrientOp,
    DreamPruneOp,
    DreamReflectOp,
)
from .lint_ops import (
    LintCommunityAnomalyOp,
    LintContradictionOp,
    LintDanglingRefOp,
    LintDataGapOp,
    LintOrphanOp,
    LintPredicateContradictionOp,
    LintStaleOp,
    LintTemporalStalenessOp,
    MergeFindingsOp,
)

__all__ = [
    "DreamConsolidateOp",
    "DreamGatherSignalOp",
    "DreamOrientOp",
    "DreamPruneOp",
    "DreamReflectOp",
    "LintCommunityAnomalyOp",
    "LintContradictionOp",
    "LintDanglingRefOp",
    "LintDataGapOp",
    "LintOrphanOp",
    "LintPredicateContradictionOp",
    "LintStaleOp",
    "LintTemporalStalenessOp",
    "MemvaultOp",
    "MergeFindingsOp",
    "PipelineMeta",
]

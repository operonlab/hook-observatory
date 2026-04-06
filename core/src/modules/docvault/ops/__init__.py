"""DocVault pipeline operators — Slot-based architecture.

Each Op implements the Operator protocol (name, input_keys, output_keys, __call__).
Ops are plugged into Slots defined in domain_profiles.py.
"""

from .cited_answer import CitedAnswerOp
from .contextual_chunk import ContextualChunkOp
from .contradiction import ContradictionDetectionOp
from .contradiction_aware import ContradictionAwareOp
from .coverage_gap import CoverageGapOp
from .fan_out import FanOutOp
from .flat_index import FlatIndexOp
from .gap_analyzer import GapAnalyzerOp
from .hierarchical_chunk import HierarchicalChunkOp
from .hybrid_rrf_search import HybridRRFSearchOp
from .intent_router import IntentRouterOp
from .jina_rerank import JinaRerankOp
from .merge import MergeOp
from .strict_cite import StrictCiteOp

__all__ = [
    "CitedAnswerOp",
    "ContextualChunkOp",
    "ContradictionAwareOp",
    "ContradictionDetectionOp",
    "CoverageGapOp",
    "FanOutOp",
    "FlatIndexOp",
    "GapAnalyzerOp",
    "HierarchicalChunkOp",
    "HybridRRFSearchOp",
    "IntentRouterOp",
    "JinaRerankOp",
    "MergeOp",
    "StrictCiteOp",
]

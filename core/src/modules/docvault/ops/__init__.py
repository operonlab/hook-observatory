"""DocVault pipeline operators — Slot-based architecture.

Each Op implements the Operator protocol (name, input_keys, output_keys, __call__).
Ops are plugged into Slots defined in domain_profiles.py.
"""

from .chunk_entity import ChunkEntityOp
from .cited_answer import CitedAnswerOp
from .community_index import CommunityIndexOp
from .contextual_chunk import ContextualChunkOp
from .contradiction import ContradictionDetectionOp
from .contradiction_aware import ContradictionAwareOp
from .coverage_gap import CoverageGapOp
from .fan_out import FanOutOp
from .flat_index import FlatIndexOp
from .gap_analyzer import GapAnalyzerOp
from .graph_search import GraphSearchOp
from .hierarchical_chunk import HierarchicalChunkOp
from .hybrid_rrf_search import HybridRRFSearchOp
from .intent_router import IntentRouterOp
from .jina_rerank import JinaRerankOp
from .merge import MergeOp
from .strict_cite import StrictCiteOp

__all__ = [
    "ChunkEntityOp",
    "CitedAnswerOp",
    "CommunityIndexOp",
    "ContextualChunkOp",
    "ContradictionAwareOp",
    "ContradictionDetectionOp",
    "CoverageGapOp",
    "FanOutOp",
    "FlatIndexOp",
    "GapAnalyzerOp",
    "GraphSearchOp",
    "HierarchicalChunkOp",
    "HybridRRFSearchOp",
    "IntentRouterOp",
    "JinaRerankOp",
    "MergeOp",
    "StrictCiteOp",
]

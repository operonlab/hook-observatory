"""DocVault domain profiles — Slot-based pipeline configuration.

Each retrieval step is a replaceable Slot. Different domains use different
Op combinations. New methods can be added as Ops without changing the pipeline framework.

5 Slots: ChunkSlot, IndexSlot, SearchSlot, RerankSlot, SynthSlot
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ======================== Slot Contract Definitions ========================


@dataclass
class SlotContract:
    """Defines the input/output schema for a pipeline slot."""

    name: str
    input_type: str
    output_type: str
    side_effects: list[str] = field(default_factory=list)
    description: str = ""


SLOT_CONTRACTS = {
    "chunk": SlotContract(
        name="ChunkSlot",
        input_type="raw_content: str",
        output_type="chunks: list[Chunk], section_tree: dict",
        description="Split raw document content into semantic chunks.",
    ),
    "index": SlotContract(
        name="IndexSlot",
        input_type="chunks: list[Chunk]",
        output_type="indexed_collection: str (Qdrant collection ref)",
        side_effects=["Qdrant upsert"],
        description="Embed and index chunks into vector store.",
    ),
    "search": SlotContract(
        name="SearchSlot",
        input_type="query_embedding: list[float]",
        output_type="candidates: list[ScoredChunk]",
        description="Retrieve candidate chunks from vector store.",
    ),
    "rerank": SlotContract(
        name="RerankSlot",
        input_type="candidates: list[ScoredChunk]",
        output_type="reranked: list[ScoredChunk]",
        description="Rerank candidates by cross-encoder or late interaction.",
    ),
    "synth": SlotContract(
        name="SynthSlot",
        input_type="question: str, evidence: list[ScoredChunk]",
        output_type="answer: str, citations: list[Citation]",
        description="Synthesize answer from evidence with citations.",
    ),
}


# ======================== Domain Profiles ========================

# Op names are strings — actual Op classes will be resolved at pipeline build time.
# This allows domain_profiles.py to be imported without circular dependencies.

DOMAIN_PROFILES: dict[str, dict[str, str]] = {
    "default": {
        "chunk": "ContextualChunkOp",
        "index": "FlatIndexOp",
        "search": "HybridRRFSearchOp",
        "rerank": "JinaRerankOp",
        "synth": "CitedAnswerOp",
    },
    "medical": {
        "chunk": "ContextualChunkOp",
        "index": "RAPTORIndexOp",
        "search": "GraphSearchOp",
        "rerank": "JinaRerankOp",
        "synth": "StrictCiteOp",
    },
    "legal": {
        "chunk": "HierarchicalChunkOp",
        "index": "RAPTORIndexOp",
        "search": "DeepReadSearchOp",
        "rerank": "JinaRerankOp",
        "synth": "ContradictionAwareOp",
    },
    "finance": {
        "chunk": "LateChunkOp",
        "index": "FlatIndexOp",
        "search": "HybridDynamicAlphaOp",
        "rerank": "ColBERTRerankOp",
        "synth": "CitedAnswerOp",
    },
}


def get_profile(domain: str = "default") -> dict[str, str]:
    """Get the Op configuration for a domain. Falls back to 'default'."""
    return DOMAIN_PROFILES.get(domain, DOMAIN_PROFILES["default"])


# ======================== Op Registry ========================
# Maps Op name strings to actual classes. Lazy imports avoid circular deps.

_OP_REGISTRY: dict[str, type] | None = None


def _build_registry() -> dict[str, type]:
    """Build the Op class registry (lazy, called once)."""
    from .ops.contradiction_aware import ContradictionAwareOp
    from .ops.hierarchical_chunk import HierarchicalChunkOp
    from .ops.strict_cite import StrictCiteOp

    return {
        # Phase 5 — implemented
        "HierarchicalChunkOp": HierarchicalChunkOp,
        "StrictCiteOp": StrictCiteOp,
        "ContradictionAwareOp": ContradictionAwareOp,
        # Stubs — will be replaced with real implementations in later phases
        # "ContextualChunkOp": ...,
        # "FlatIndexOp": ...,
        # "HybridRRFSearchOp": ...,
        # "JinaRerankOp": ...,
        # "CitedAnswerOp": ...,
        # Phase 6+ (not yet implemented)
        # "LateChunkOp": ...,
        # "RAPTORIndexOp": ...,
        # "DeepReadSearchOp": ...,
        # "GraphSearchOp": ...,
        # "HybridDynamicAlphaOp": ...,
        # "ColBERTRerankOp": ...,
    }


def resolve_op(op_name: str) -> type | None:
    """Resolve an Op name string to its class. Returns None if not registered."""
    global _OP_REGISTRY
    if _OP_REGISTRY is None:
        _OP_REGISTRY = _build_registry()
    return _OP_REGISTRY.get(op_name)


def list_profiles() -> list[dict[str, str]]:
    """List all available domain profiles with their Op names."""
    result = []
    for name, profile in DOMAIN_PROFILES.items():
        result.append({"domain": name, **profile})
    return result


def build_qa_pipeline_config(domain: str = "default") -> dict[str, Any]:
    """Build QA pipeline configuration for a domain.

    Returns a config dict that Pipeline A will use to assemble operators.
    Actual pipeline assembly happens in qa_service.py (Phase 1+).
    """
    profile = get_profile(domain)
    return {
        "domain": domain,
        "fixed_ops": [
            "EmbedOp",
            "IntentRouterOp",
            "RecencyOp",
            "SemanticBoostOp",
            "MinScoreOp",
            "CRAGOp",
        ],
        "slots": {
            "search": profile["search"],
            "rerank": profile["rerank"],
            "synth": profile["synth"],
        },
    }


def build_ingest_pipeline_config(domain: str = "default") -> dict[str, Any]:
    """Build ingestion pipeline configuration for a domain.

    Returns a config dict for document parsing → chunking → indexing → enrichment.
    """
    profile = get_profile(domain)
    return {
        "domain": domain,
        "fixed_ops": ["DocumentParserOp", "EnrichmentOp"],
        "slots": {
            "chunk": profile["chunk"],
            "index": profile["index"],
        },
    }

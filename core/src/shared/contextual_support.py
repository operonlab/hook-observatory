"""Contextual Support Tracking — lightweight evidence chain utility.

Cannibalized from memory-lancedb-pro's SmartMemoryMetadata.contextual_support
pattern (G9). Tracks per-context confirm/contradict/neutral relationships with
strength scoring to build an evidence chain around a memory.

Design:
  - Pure utility — no DB, no async, no imports from other modules
  - Dataclasses follow scoring_pipeline.py style
  - Evidence can be serialized to JSON and stored in any metadata JSONB field
  - compute_net_confidence() applies temporal decay on individual evidence items
    (recent evidence counts more; older evidence fades over a 90-day half-life)

Usage example (in kg_services.py):
    from src.shared.contextual_support import (
        ContextualEvidence, EvidenceChain, SupportRelation,
        add_evidence, compute_net_confidence, summarize_evidence,
    )

    # Build an evidence chain for a wisdom node
    chain = EvidenceChain(target_id=wisdom_node.id)
    for triple in confirming_triples:
        chain = add_evidence(
            chain,
            ContextualEvidence(
                context_id=triple.id,
                relation=SupportRelation.CONFIRMS,
                strength=0.8,
                timestamp=triple.created_at,
                source_text=f"{triple.subject} {triple.predicate} {triple.object}",
            ),
        )
    print(summarize_evidence(chain))
    # "3 confirm, 1 contradict, 0 neutral — net confidence 0.72"
"""

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# Half-life for temporal decay applied to individual evidence items (days).
# Evidence older than this loses roughly 50% of its weight.
_EVIDENCE_HALF_LIFE_DAYS: float = 90.0


# ---------------------------------------------------------------------------
# SupportRelation
# ---------------------------------------------------------------------------


class SupportRelation(StrEnum):
    """Direction of a context's relationship to the target memory."""

    CONFIRMS = "confirms"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"


# ---------------------------------------------------------------------------
# ContextualEvidence
# ---------------------------------------------------------------------------


@dataclass
class ContextualEvidence:
    """A single context entry that supports or opposes a target memory.

    Attributes:
        context_id:  ID of the source block / triple / session that provides
                     this evidence (points back to the authoritative record).
        relation:    Whether the context confirms, contradicts, or is neutral
                     toward the target memory.
        strength:    Raw evidence strength before temporal decay, in [0.0, 1.0].
                     Higher = stronger signal.
        timestamp:   When this evidence was observed.  Used for temporal decay.
        source_text: Optional brief excerpt from the source for display / debug.
    """

    context_id: str
    relation: SupportRelation
    strength: float  # 0.0-1.0
    timestamp: datetime
    source_text: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"ContextualEvidence.strength must be in [0, 1], got {self.strength}")

    def effective_strength(self, now: datetime | None = None) -> float:
        """Return strength after applying temporal decay.

        Uses exponential half-life decay: w = strength * 2^(-age / half_life).
        Clamps result to [0.0, 1.0].
        """
        _now = now or datetime.now(UTC)
        ts = self.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        age_days = (_now - ts).total_seconds() / 86400.0
        age_days = max(age_days, 0.0)
        decay = math.pow(2.0, -age_days / _EVIDENCE_HALF_LIFE_DAYS)
        return float(max(0.0, min(1.0, self.strength * decay)))

    # --- Serialization helpers ---

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSONB storage."""
        return {
            "context_id": self.context_id,
            "relation": self.relation.value,
            "strength": self.strength,
            "timestamp": self.timestamp.isoformat(),
            "source_text": self.source_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextualEvidence":
        """Deserialize from a plain dict (e.g., loaded from JSONB metadata)."""
        ts_raw = data["timestamp"]
        if isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw)
        else:
            ts = ts_raw
        return cls(
            context_id=data["context_id"],
            relation=SupportRelation(data["relation"]),
            strength=float(data["strength"]),
            timestamp=ts,
            source_text=data.get("source_text"),
        )


# ---------------------------------------------------------------------------
# EvidenceChain
# ---------------------------------------------------------------------------


@dataclass
class EvidenceChain:
    """Aggregate evidence for a single target memory.

    Attributes:
        target_id:      ID of the memory / triple / node being evaluated.
        evidence:       All collected ContextualEvidence entries.
        net_confidence: Computed confidence score in [0.0, 1.0].  Call
                        recompute() or use add_evidence() to keep it fresh.
    """

    target_id: str
    evidence: list[ContextualEvidence] = field(default_factory=list)
    net_confidence: float = 0.5  # Default: uncertain until evidence accumulates

    def recompute(self, now: datetime | None = None) -> None:
        """Recompute net_confidence from current evidence list in-place."""
        self.net_confidence = compute_net_confidence(self.evidence, now=now)

    @property
    def confirm_count(self) -> int:
        return sum(1 for e in self.evidence if e.relation == SupportRelation.CONFIRMS)

    @property
    def contradict_count(self) -> int:
        return sum(1 for e in self.evidence if e.relation == SupportRelation.CONTRADICTS)

    @property
    def neutral_count(self) -> int:
        return sum(1 for e in self.evidence if e.relation == SupportRelation.NEUTRAL)

    # --- Serialization helpers ---

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "evidence": [e.to_dict() for e in self.evidence],
            "net_confidence": self.net_confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceChain":
        chain = cls(
            target_id=data["target_id"],
            net_confidence=float(data.get("net_confidence", 0.5)),
        )
        chain.evidence = [ContextualEvidence.from_dict(e) for e in data.get("evidence", [])]
        return chain


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def compute_net_confidence(
    evidence_list: list[ContextualEvidence],
    now: datetime | None = None,
) -> float:
    """Compute net confidence from a list of evidence entries.

    Algorithm:
      1. Each item's effective weight = effective_strength() (includes temporal decay).
      2. CONFIRMS items contribute +weight to the numerator.
         CONTRADICTS items contribute -weight.
         NEUTRAL items contribute 0 (they provide no directional signal).
      3. Total positive possible weight = sum of all effective weights (confirms + contradicts).
      4. net_confidence = 0.5 + (raw_score / 2 * total_weight)
         → mapped to [0, 1] centred at 0.5 when evidence is balanced or absent.

    Returns:
        float in [0.0, 1.0].  0.5 = no directional evidence or perfectly balanced.
    """
    if not evidence_list:
        return 0.5

    _now = now or datetime.now(UTC)

    raw_score: float = 0.0
    total_weight: float = 0.0

    for ev in evidence_list:
        w = ev.effective_strength(now=_now)
        if ev.relation == SupportRelation.CONFIRMS:
            raw_score += w
            total_weight += w
        elif ev.relation == SupportRelation.CONTRADICTS:
            raw_score -= w
            total_weight += w
        # NEUTRAL: skip — no directional contribution

    if total_weight == 0.0:
        return 0.5

    # Normalise to [0, 1]: raw_score ∈ [-total_weight, +total_weight]
    normalised = raw_score / total_weight  # ∈ [-1.0, +1.0]
    confidence = 0.5 + normalised * 0.5  # ∈ [0.0,  1.0]
    return round(float(max(0.0, min(1.0, confidence))), 4)


def add_evidence(
    chain: EvidenceChain,
    new_evidence: ContextualEvidence,
    now: datetime | None = None,
) -> EvidenceChain:
    """Append a new evidence entry to the chain and recompute net_confidence.

    Returns the updated chain (mutates in-place and also returns it for
    convenient chaining: chain = add_evidence(chain, ev)).
    """
    chain.evidence.append(new_evidence)
    chain.recompute(now=now)
    return chain


def summarize_evidence(chain: EvidenceChain) -> str:
    """Return a human-readable one-line summary of the evidence chain.

    Example: "3 confirm, 1 contradict, 0 neutral — net confidence 0.72"
    """
    c = chain.confirm_count
    d = chain.contradict_count
    n = chain.neutral_count
    conf = chain.net_confidence
    return f"{c} confirm, {d} contradict, {n} neutral \u2014 net confidence {conf:.2f}"

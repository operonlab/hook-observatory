"""Multi-stage scoring pipeline for memvault search results.

Inspired by memory-lancedb-pro's 7-stage scoring system.
Each stage is independently bypassable and try-catch isolated.

G3 enhancement: Weibull decay replaces linear time decay for more
realistic memory forgetting curves with tier-aware parameters.

G6 enhancement: Access reinforcement — frequently-accessed memories
decay more slowly via compute_effective_half_life() from access_tracker.
Results dicts should carry access_count and last_accessed_at for this
stage to take effect (populated by services.py search queries).
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.shared.access_tracker import compute_effective_half_life

from .noise_filter import check_noise

logger = logging.getLogger(__name__)

# --- Weibull decay parameters per memory tier ---
# β (shape): <1 = rapid early decay, 1 = exponential, >1 = slow then fast
# λ (scale): characteristic lifetime in days
# floor: minimum decay factor (memory never fully forgotten)
WEIBULL_PARAMS = {
    "core": {"beta": 0.8, "lambda_": 180.0, "floor": 0.4},
    "hot": {"beta": 1.0, "lambda_": 60.0, "floor": 0.3},
    "warm": {"beta": 1.2, "lambda_": 30.0, "floor": 0.2},
    "cold": {"beta": 1.5, "lambda_": 14.0, "floor": 0.1},
}

# --- Access reinforcement defaults (G6) ---
# Base half-life used when adjusting Weibull λ via access reinforcement.
# The effective λ replaces the tier's lambda_ when access_count > 0.
_ACCESS_BASE_HALF_LIFE_DAYS: float = 30.0


def weibull_decay(age_days: float, tier: str = "hot") -> float:
    """Compute Weibull survival function for memory decay.

    S(t) = floor + (1 - floor) * exp(-(t/λ)^β)
    """
    params = WEIBULL_PARAMS.get(tier, WEIBULL_PARAMS["hot"])
    beta = params["beta"]
    lambda_ = params["lambda_"]
    floor = params["floor"]

    if age_days <= 0:
        return 1.0

    survival = math.exp(-((age_days / lambda_) ** beta))
    return floor + (1 - floor) * survival


def weibull_decay_with_half_life(
    age_days: float, effective_half_life: float, tier: str = "hot"
) -> float:
    """Weibull decay with an access-adjusted characteristic lifetime.

    Replaces the tier's default lambda_ with effective_half_life so that
    frequently-accessed memories decay more slowly.
    """
    params = WEIBULL_PARAMS.get(tier, WEIBULL_PARAMS["hot"])
    beta = params["beta"]
    floor = params["floor"]

    if age_days <= 0:
        return 1.0

    # Use effective half-life as the scale parameter (λ)
    survival = math.exp(-((age_days / effective_half_life) ** beta))
    return floor + (1 - floor) * survival


@dataclass
class ScoringConfig:
    recency_half_life: float = 14.0
    recency_weight: float = 0.15
    length_anchor: int = 500
    min_score: float = 0.10
    mmr_threshold: float = 0.85
    semantic_boost: float = 0.3
    trust_penalty: float = 0.3  # max penalty for low-trust memories
    feedback_weight: float = 0.15  # max boost/penalty from feedback signals
    stages_enabled: dict[str, bool] = field(
        default_factory=lambda: {
            "recency": True,
            "importance": True,
            "trust_boost": True,
            "feedback_boost": True,
            "length_norm": True,
            "time_decay": True,
            "semantic_boost": True,
            "min_score": True,
            "noise_filter": True,
            "mmr": True,
        }
    )


@dataclass
class ScoringMetadata:
    stages_applied: list[str] = field(default_factory=list)
    stages_skipped: list[str] = field(default_factory=list)
    noise_filtered: int = 0
    mmr_deduped: int = 0
    input_count: int = 0
    output_count: int = 0


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Delegates to shared scoring_stages.cosine_similarity.
    """
    from src.shared.scoring_stages import cosine_similarity

    return cosine_similarity(a, b)


class ScoringPipeline:
    def __init__(self, config: ScoringConfig | None = None):
        self.config = config or ScoringConfig()

    def _is_enabled(self, stage: str) -> bool:
        return self.config.stages_enabled.get(stage, True)

    def apply(
        self,
        results: list[dict],
        query_embedding: list[float] | None = None,
    ) -> tuple[list[dict], ScoringMetadata]:
        """Apply all enabled stages.

        Each result dict has: block, score, content, created_at, confidence, embedding (optional).
        G6 fields (optional): access_count, last_accessed_at — used by time_decay stage.
        """
        meta = ScoringMetadata(input_count=len(results))

        if not results:
            meta.output_count = 0
            return results, meta

        now = datetime.now(UTC)

        # Stage 1: Recency Boost
        results = self._run_stage("recency", results, meta, self._apply_recency, now=now)

        # Stage 2: Importance Weight
        results = self._run_stage("importance", results, meta, self._apply_importance)

        # Stage 2.5: Trust Boost (P3 source tracking → scoring)
        results = self._run_stage("trust_boost", results, meta, self._apply_trust_boost)

        # Stage 2.75: Feedback Boost (closed-loop learning from explicit feedback)
        results = self._run_stage("feedback_boost", results, meta, self._apply_feedback_boost)

        # Stage 3: Length Normalization
        results = self._run_stage("length_norm", results, meta, self._apply_length_norm)

        # Stage 4: Time Decay (G3 Weibull + G6 access reinforcement)
        results = self._run_stage("time_decay", results, meta, self._apply_time_decay)

        # Stage 4.5: Semantic Relevance Boost (FadeMem-inspired)
        results = self._run_stage(
            "semantic_boost",
            results,
            meta,
            self._apply_semantic_relevance,
            query_embedding=query_embedding,
        )

        # Stage 5: Hard Min Score
        results = self._run_stage("min_score", results, meta, self._apply_min_score)

        # Stage 6: Noise Filter
        before_noise = len(results)
        results = self._run_stage("noise_filter", results, meta, self._apply_noise_filter)
        meta.noise_filtered = before_noise - len(results)

        # Stage 7: MMR Diversity
        before_mmr = len(results)
        results = self._run_stage(
            "mmr", results, meta, self._apply_mmr, query_embedding=query_embedding
        )
        meta.mmr_deduped = before_mmr - len(results)

        # Sort by final score descending
        results.sort(key=lambda r: r["score"], reverse=True)
        meta.output_count = len(results)
        return results, meta

    def _run_stage(
        self,
        name: str,
        results: list[dict],
        meta: ScoringMetadata,
        fn: ...,
        **kwargs: ...,
    ) -> list[dict]:
        if not self._is_enabled(name):
            meta.stages_skipped.append(name)
            return results
        try:
            results = fn(results, **kwargs)
            meta.stages_applied.append(name)
        except Exception:
            logger.exception("Scoring stage '%s' failed, skipping", name)
            meta.stages_skipped.append(name)
        return results

    def _apply_recency(self, results: list[dict], now: datetime) -> list[dict]:
        from src.shared.scoring_stages import apply_recency_boost

        return apply_recency_boost(
            results,
            half_life_days=self.config.recency_half_life,
            weight=self.config.recency_weight,
            now=now,
        )

    def _apply_importance(self, results: list[dict]) -> list[dict]:
        for r in results:
            confidence = r.get("confidence") or 0.5  # unset → neutral
            r["score"] *= 0.7 + 0.3 * confidence
        return results

    def _apply_trust_boost(self, results: list[dict]) -> list[dict]:
        """P3 source tracking → scoring integration.

        Compute trust_score from source_tracker provenance heuristics.
        Low-trust memories get penalized; high-trust memories are unaffected.
        Formula: score *= (1 - trust_penalty * (1 - trust_score))
        """
        from .source_tracker import MemoryProvenance, compute_trust_score

        for r in results:
            block = r.get("block")
            if not block:
                continue
            # Build provenance from available block metadata
            session_id = getattr(block, "source_session", None)
            provenance = MemoryProvenance(
                source_session_id=session_id,
                extraction_method="auto_extract" if session_id else "manual",
            )
            trust = compute_trust_score(provenance)
            # Apply penalty: trust=1.0 → no penalty, trust=0.5 → 15% penalty (default)
            r["score"] *= 1.0 - self.config.trust_penalty * (1.0 - trust)
        return results

    def _apply_feedback_boost(self, results: list[dict]) -> list[dict]:
        """Closed-loop learning: adjust scores based on accumulated explicit feedback.

        Result dict optional field:
          feedback_net (int) — net signal (positive_count - negative_count).
                               Populated by services.py before calling pipeline.

        Formula: score *= 1 + feedback_weight * tanh(net_signal / 3)
        - tanh saturates smoothly: ±3 signals ≈ ±14% boost, ±10 ≈ ±15%
        - Division by 3 controls sensitivity (3 signals for ~70% of max effect)
        """
        for r in results:
            net = r.get("feedback_net") or 0  # handles None and missing key safely
            if not net:
                continue
            r["score"] *= 1.0 + self.config.feedback_weight * math.tanh(net / 3.0)
        return results

    def _apply_length_norm(self, results: list[dict]) -> list[dict]:
        from src.shared.scoring_stages import apply_length_normalization

        return apply_length_normalization(
            results,
            anchor_length=self.config.length_anchor,
        )

    def _apply_time_decay(self, results: list[dict]) -> list[dict]:
        """Weibull decay with G6 access reinforcement.

        G3: tier-aware Weibull forgetting curve (confidence → tier).
        G6: effective half-life replaces fixed λ when access data is present.

        Result dict optional fields for G6:
          access_count (int)       — number of times block was retrieved
          last_accessed_at (datetime | None) — timestamp of last access
        """
        now = datetime.now(UTC)
        for r in results:
            created_at = r.get("created_at")
            if not created_at:
                continue

            age_days = max((now - created_at).total_seconds() / 86400, 0)

            # Determine tier from confidence (G3 logic unchanged)
            confidence = r.get("confidence") or 0.5
            if confidence >= 0.8:
                tier = "core"
            elif confidence >= 0.5:
                tier = "hot"
            elif confidence >= 0.3:
                tier = "warm"
            else:
                tier = "cold"

            # G6: if access tracking data is present, compute effective half-life
            access_count: int = r.get("access_count") or 0
            last_accessed_at = r.get("last_accessed_at")

            if access_count > 0 and last_accessed_at is not None:
                # Use tier's default λ as the base for effective half-life
                tier_lambda = WEIBULL_PARAMS.get(tier, WEIBULL_PARAMS["hot"])["lambda_"]
                effective_hl = compute_effective_half_life(
                    access_count=access_count,
                    last_accessed_at=last_accessed_at,
                    created_at=created_at,
                    base_half_life_days=tier_lambda,
                )
                r["score"] *= weibull_decay_with_half_life(age_days, effective_hl, tier)
            else:
                # Fallback: standard Weibull decay (G3 behaviour)
                r["score"] *= weibull_decay(age_days, tier)

        return results

    def _apply_semantic_relevance(
        self,
        results: list[dict],
        query_embedding: list[float] | None = None,
    ) -> list[dict]:
        """FadeMem-inspired: boost scores for memories semantically close to query.

        If query_embedding is available, compute cosine similarity between each
        result's embedding and the query. Higher similarity = less decay penalty.

        Formula: score *= (1 + semantic_boost_factor * similarity)
        where semantic_boost_factor defaults to 0.3
        """
        if not query_embedding:
            return results

        for r in results:
            emb = r.get("embedding")
            if not emb:
                continue
            similarity = _cosine_similarity(emb, query_embedding)
            # similarity is in [-1, 1]; clamp to [0, 1] for boost calculation
            similarity = max(0.0, similarity)
            r["score"] *= 1.0 + self.config.semantic_boost * similarity

        return results

    def _apply_min_score(self, results: list[dict]) -> list[dict]:
        from src.shared.scoring_stages import apply_min_score_filter

        return apply_min_score_filter(results, min_score=self.config.min_score)

    def _apply_noise_filter(self, results: list[dict]) -> list[dict]:
        clean = []
        for r in results:
            content = r.get("content", "")
            verdict = check_noise(content)
            if not verdict.is_noise:
                clean.append(r)
        return clean

    def _apply_mmr(
        self,
        results: list[dict],
        query_embedding: list[float] | None = None,
    ) -> list[dict]:
        """MMR diversity: if cosine_similarity > threshold, reduce lower-ranked score by 50%."""
        if not query_embedding:
            return results

        # Collect results that have embeddings
        to_remove = set()
        for i in range(len(results)):
            if i in to_remove:
                continue
            emb_i = results[i].get("embedding")
            if not emb_i:
                continue
            for j in range(i + 1, len(results)):
                if j in to_remove:
                    continue
                emb_j = results[j].get("embedding")
                if not emb_j:
                    continue
                sim = _cosine_similarity(emb_i, emb_j)
                if sim > self.config.mmr_threshold:
                    # Reduce lower-ranked one's score by 50%
                    results[j]["score"] *= 0.5
                    # If score drops below min_score, mark for removal
                    if results[j]["score"] < self.config.min_score:
                        to_remove.add(j)

        return [r for i, r in enumerate(results) if i not in to_remove]

"""Multi-stage scoring pipeline for memvault search results.

Inspired by memory-lancedb-pro's 7-stage scoring system.
Each stage is independently bypassable and try-catch isolated.

G3 enhancement: Weibull decay replaces linear time decay for more
realistic memory forgetting curves with tier-aware parameters.

G6 enhancement: Access reinforcement — frequently-accessed memories
decay more slowly via compute_effective_half_life() from access_tracker.
Results dicts should carry access_count and last_accessed_at for this
stage to take effect (populated by services.py search queries).

Reactive Protocol: Each stage is a ScoringOp implementing the Operator protocol.
ScoringPipeline.apply() uses Pipeline.pipe() for composable execution with
compile() validation for key dependency chains.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.shared.access_tracker import compute_effective_half_life
from src.shared.reactive import Pipeline

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


# ═══════════════════════════════════════════════════════════════════════════
# Scoring Operators — each implements the Operator protocol from reactive.py
# ═══════════════════════════════════════════════════════════════════════════


class ScoringOp:
    """Base for scoring pipeline operators (Operator protocol).

    Wraps each stage with enable-check + try/except error isolation.
    Provides both async __call__ (Protocol compliance) and sync
    execute_stage() for ScoringPipeline's synchronous apply().
    """

    def __init__(self, stage_name: str, config: ScoringConfig) -> None:
        self._stage_name = stage_name
        self._config = config

    @property
    def name(self) -> str:
        return self._stage_name

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("results",)

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("results",)

    def execute_stage(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Sync execution with enable-check + error isolation."""
        meta: ScoringMetadata = ctx["meta"]
        if not self._config.stages_enabled.get(self._stage_name, True):
            meta.stages_skipped.append(self._stage_name)
            return ctx
        try:
            ctx["results"] = self.transform(ctx["results"], ctx)
            meta.stages_applied.append(self._stage_name)
        except Exception:
            logger.exception("Scoring stage '%s' failed, skipping", self._stage_name)
            meta.stages_skipped.append(self._stage_name)
        return ctx

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Async path (Operator Protocol compliance)."""
        return self.execute_stage(ctx)

    def transform(self, results: list[dict], ctx: dict[str, Any]) -> list[dict]:
        raise NotImplementedError


class RecencyOp(ScoringOp):
    """Stage 1: Recency Boost — newer memories score higher."""

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("results", "now")

    def transform(self, results: list[dict], ctx: dict[str, Any]) -> list[dict]:
        from src.shared.scoring_stages import apply_recency_boost

        return apply_recency_boost(
            results,
            half_life_days=self._config.recency_half_life,
            weight=self._config.recency_weight,
            now=ctx["now"],
        )


class ImportanceOp(ScoringOp):
    """Stage 2: Importance Weight — confidence-based scoring."""

    def transform(self, results: list[dict], ctx: dict[str, Any]) -> list[dict]:
        for r in results:
            confidence = r.get("confidence") or 0.5  # unset → neutral
            r["score"] *= 0.7 + 0.3 * confidence
        return results


class TrustBoostOp(ScoringOp):
    """Stage 2.5: Trust Boost — P3 source tracking → scoring integration."""

    def transform(self, results: list[dict], ctx: dict[str, Any]) -> list[dict]:
        from .source_tracker import MemoryProvenance, compute_trust_score

        for r in results:
            block = r.get("block")
            if not block:
                continue
            session_id = getattr(block, "source_session", None)
            provenance = MemoryProvenance(
                source_session_id=session_id,
                extraction_method="auto_extract" if session_id else "manual",
            )
            trust = compute_trust_score(provenance)
            r["score"] *= 1.0 - self._config.trust_penalty * (1.0 - trust)
        return results


class FeedbackBoostOp(ScoringOp):
    """Stage 2.75: Feedback Boost — closed-loop learning from explicit feedback.

    Formula: score *= 1 + feedback_weight * tanh(net_signal / 3)
    """

    def transform(self, results: list[dict], ctx: dict[str, Any]) -> list[dict]:
        for r in results:
            net = r.get("feedback_net") or 0
            if not net:
                continue
            r["score"] *= 1.0 + self._config.feedback_weight * math.tanh(net / 3.0)
        return results


class LengthNormOp(ScoringOp):
    """Stage 3: Length Normalization — penalize extreme content lengths."""

    def transform(self, results: list[dict], ctx: dict[str, Any]) -> list[dict]:
        from src.shared.scoring_stages import apply_length_normalization

        return apply_length_normalization(
            results,
            anchor_length=self._config.length_anchor,
        )


class TimeDecayOp(ScoringOp):
    """Stage 4: Time Decay — G3 Weibull + G6 access reinforcement."""

    def transform(self, results: list[dict], ctx: dict[str, Any]) -> list[dict]:
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
                tier_lambda = WEIBULL_PARAMS.get(tier, WEIBULL_PARAMS["hot"])["lambda_"]
                effective_hl = compute_effective_half_life(
                    access_count=access_count,
                    last_accessed_at=last_accessed_at,
                    created_at=created_at,
                    base_half_life_days=tier_lambda,
                )
                r["score"] *= weibull_decay_with_half_life(age_days, effective_hl, tier)
            else:
                r["score"] *= weibull_decay(age_days, tier)

        return results


class SemanticBoostOp(ScoringOp):
    """Stage 4.5: Semantic Relevance Boost — FadeMem-inspired."""

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("results", "query_embedding")

    def transform(self, results: list[dict], ctx: dict[str, Any]) -> list[dict]:
        query_embedding = ctx.get("query_embedding")
        if not query_embedding:
            return results

        for r in results:
            emb = r.get("embedding")
            if not emb:
                continue
            similarity = _cosine_similarity(emb, query_embedding)
            similarity = max(0.0, similarity)
            r["score"] *= 1.0 + self._config.semantic_boost * similarity

        return results


class MinScoreOp(ScoringOp):
    """Stage 5: Hard Min Score — remove results below threshold."""

    def transform(self, results: list[dict], ctx: dict[str, Any]) -> list[dict]:
        from src.shared.scoring_stages import apply_min_score_filter

        return apply_min_score_filter(results, min_score=self._config.min_score)


class NoiseFilterOp(ScoringOp):
    """Stage 6: Noise Filter — remove greeting/noise content."""

    def execute_stage(self, ctx: dict[str, Any]) -> dict[str, Any]:
        meta: ScoringMetadata = ctx["meta"]
        if not self._config.stages_enabled.get(self._stage_name, True):
            meta.stages_skipped.append(self._stage_name)
            return ctx
        try:
            before = len(ctx["results"])
            ctx["results"] = self.transform(ctx["results"], ctx)
            meta.stages_applied.append(self._stage_name)
            meta.noise_filtered = before - len(ctx["results"])
        except Exception:
            logger.exception("Scoring stage '%s' failed, skipping", self._stage_name)
            meta.stages_skipped.append(self._stage_name)
        return ctx

    def transform(self, results: list[dict], ctx: dict[str, Any]) -> list[dict]:
        clean = []
        for r in results:
            content = r.get("content", "")
            verdict = check_noise(content)
            if not verdict.is_noise:
                clean.append(r)
        return clean


class MMROp(ScoringOp):
    """Stage 7: MMR Diversity — reduce redundant results."""

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("results", "query_embedding")

    def execute_stage(self, ctx: dict[str, Any]) -> dict[str, Any]:
        meta: ScoringMetadata = ctx["meta"]
        if not self._config.stages_enabled.get(self._stage_name, True):
            meta.stages_skipped.append(self._stage_name)
            return ctx
        try:
            before = len(ctx["results"])
            ctx["results"] = self.transform(ctx["results"], ctx)
            meta.stages_applied.append(self._stage_name)
            meta.mmr_deduped = before - len(ctx["results"])
        except Exception:
            logger.exception("Scoring stage '%s' failed, skipping", self._stage_name)
            meta.stages_skipped.append(self._stage_name)
        return ctx

    def transform(self, results: list[dict], ctx: dict[str, Any]) -> list[dict]:
        query_embedding = ctx.get("query_embedding")
        if not query_embedding:
            return results

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
                if sim > self._config.mmr_threshold:
                    results[j]["score"] *= 0.5
                    if results[j]["score"] < self._config.min_score:
                        to_remove.add(j)

        return [r for i, r in enumerate(results) if i not in to_remove]


# ═══════════════════════════════════════════════════════════════════════════
# ScoringPipeline — public API (unchanged)
# ═══════════════════════════════════════════════════════════════════════════


class ScoringPipeline:
    def __init__(self, config: ScoringConfig | None = None):
        self.config = config or ScoringConfig()

    def _build_pipeline(self) -> Pipeline:
        """Build the reactive Pipeline with all 10 scoring operators."""
        return Pipeline().pipe(
            RecencyOp("recency", self.config),
            ImportanceOp("importance", self.config),
            TrustBoostOp("trust_boost", self.config),
            FeedbackBoostOp("feedback_boost", self.config),
            LengthNormOp("length_norm", self.config),
            TimeDecayOp("time_decay", self.config),
            SemanticBoostOp("semantic_boost", self.config),
            MinScoreOp("min_score", self.config),
            NoiseFilterOp("noise_filter", self.config),
            MMROp("mmr", self.config),
        )

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

        ctx: dict[str, Any] = {
            "results": results,
            "meta": meta,
            "now": datetime.now(UTC),
            "query_embedding": query_embedding,
        }

        pipeline = self._build_pipeline()

        # Sync execution via execute_stage()
        for op in pipeline:
            ctx = op.execute_stage(ctx)

        # Sort by final score descending
        results = ctx["results"]
        results.sort(key=lambda r: r["score"], reverse=True)
        meta.output_count = len(results)
        return results, meta

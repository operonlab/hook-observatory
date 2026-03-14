"""Multi-stage scoring pipeline for memvault search results.

Inspired by memory-lancedb-pro's 7-stage scoring system.
Each stage is independently bypassable and try-catch isolated.

G3 enhancement: Weibull decay replaces linear time decay for more
realistic memory forgetting curves with tier-aware parameters.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

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


@dataclass
class ScoringConfig:
    recency_half_life: float = 14.0
    recency_weight: float = 0.15
    length_anchor: int = 500
    min_score: float = 0.10
    mmr_threshold: float = 0.85
    stages_enabled: dict[str, bool] = field(
        default_factory=lambda: {
            "recency": True,
            "importance": True,
            "length_norm": True,
            "time_decay": True,
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
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


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

        # Stage 3: Length Normalization
        results = self._run_stage("length_norm", results, meta, self._apply_length_norm)

        # Stage 4: Time Decay
        results = self._run_stage("time_decay", results, meta, self._apply_time_decay)

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
        for r in results:
            created_at = r.get("created_at")
            if created_at:
                age_days = max((now - created_at).total_seconds() / 86400, 0)
                boost = 1.0 + self.config.recency_weight * math.exp(
                    -age_days / self.config.recency_half_life
                )
                r["score"] *= boost
        return results

    def _apply_importance(self, results: list[dict]) -> list[dict]:
        for r in results:
            confidence = r.get("confidence") or 0.5  # unset → neutral
            r["score"] *= 0.7 + 0.3 * confidence
        return results

    def _apply_length_norm(self, results: list[dict]) -> list[dict]:
        for r in results:
            content = r.get("content", "")
            content_len = max(len(content), 1)
            ratio = content_len / self.config.length_anchor
            # Use abs(log2) to penalize both very short and very long content
            r["score"] *= 1.0 / (1.0 + 0.3 * abs(math.log2(ratio)))
        return results

    def _apply_time_decay(self, results: list[dict]) -> list[dict]:
        """Weibull decay: tier-aware forgetting curve replaces linear decay.

        G3 cannibalization from memory-lancedb-pro.
        Determines tier from block confidence:
          confidence >= 0.8 → core (slowest decay)
          confidence >= 0.5 → hot (default)
          confidence >= 0.3 → warm
          else → cold (fastest decay)
        """
        now = datetime.now(UTC)
        for r in results:
            created_at = r.get("created_at")
            if created_at:
                age_days = max((now - created_at).total_seconds() / 86400, 0)
                # Determine tier from confidence
                confidence = r.get("confidence") or 0.5
                if confidence >= 0.8:
                    tier = "core"
                elif confidence >= 0.5:
                    tier = "hot"
                elif confidence >= 0.3:
                    tier = "warm"
                else:
                    tier = "cold"
                r["score"] *= weibull_decay(age_days, tier)
        return results

    def _apply_min_score(self, results: list[dict]) -> list[dict]:
        return [r for r in results if r["score"] >= self.config.min_score]

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

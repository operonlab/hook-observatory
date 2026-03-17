"""Cross-encoder reranking for memvault.

Uses Jina Reranker v3 (0.6B, MLX-native) via persistent subprocess worker.
True cross-encoder: query and document are jointly encoded with cross-attention,
producing more accurate relevance scores than bi-encoder cosine similarity.

Includes circuit breaker for graceful degradation — falls back to original
scoring when the reranker is unavailable.
"""

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RerankerConfig:
    enabled: bool = True
    max_candidates: int = 20  # Only rerank top N
    snippet_length: int = 500  # Truncate content to this length
    weight_original: float = 0.3  # Weight of original score
    weight_rerank: float = 0.7  # Weight of cross-encoder score
    # Circuit breaker
    failure_threshold: int = 3
    recovery_seconds: float = 600  # 10 minutes


class CircuitBreaker:
    """Simple circuit breaker for reranker failures."""

    def __init__(self, threshold: int = 3, recovery: float = 600):
        self.threshold = threshold
        self.recovery = recovery
        self.failures = 0
        self.last_failure: float = 0
        self.open = False

    def record_failure(self):
        self.failures += 1
        self.last_failure = time.time()
        if self.failures >= self.threshold:
            self.open = True

    def record_success(self):
        self.failures = 0
        self.open = False

    def is_available(self) -> bool:
        if not self.open:
            return True
        # Check if recovery period has passed
        if time.time() - self.last_failure > self.recovery:
            self.open = False
            self.failures = 0
            return True
        return False


class LocalReranker:
    """Rerank search results using Jina cross-encoder via MLX bridge."""

    def __init__(self, config: RerankerConfig | None = None):
        self.config = config or RerankerConfig()
        self._breaker = CircuitBreaker(
            self.config.failure_threshold,
            self.config.recovery_seconds,
        )

    async def rerank(
        self,
        query: str,
        results: list[dict],
    ) -> tuple[list[dict], bool]:
        """Rerank results using Jina cross-encoder.

        Returns (reranked_results, was_applied).
        If reranking fails or circuit breaker is open, returns original results unchanged.
        """
        if not self.config.enabled or not self._breaker.is_available():
            return results, False

        if len(results) <= 1:
            return results, False

        try:
            from src.shared import rerank_bridge

            # Limit candidates
            candidates = results[: self.config.max_candidates]
            remainder = results[self.config.max_candidates :]

            # Prepare document snippets for cross-encoder
            snippets = [r.get("content", "")[: self.config.snippet_length] for r in candidates]

            # Call cross-encoder
            scores = await rerank_bridge.rerank(query, snippets)
            if scores is None:
                self._breaker.record_failure()
                return results, False

            # Build index→score map
            score_map = {s["index"]: s["score"] for s in scores}

            if len(scores) != len(candidates):
                logger.warning(
                    "Rerank score count mismatch: sent %d, got %d",
                    len(candidates),
                    len(scores),
                )

            # Blend original score with cross-encoder score
            for i, r in enumerate(candidates):
                ce_score = score_map.get(i)
                if ce_score is not None:
                    # Normalize cross-encoder score from [-1, 1] to [0, 1]
                    ce_normalized = (ce_score + 1) / 2
                    r["score"] = (
                        self.config.weight_original * r["score"]
                        + self.config.weight_rerank * ce_normalized
                    )

            # Re-sort candidates by new score
            candidates.sort(key=lambda r: r["score"], reverse=True)

            self._breaker.record_success()
            return candidates + remainder, True

        except Exception:
            logger.exception("Reranking failed")
            self._breaker.record_failure()
            return results, False


# Module singleton
_reranker = LocalReranker()


async def rerank_results(query: str, results: list[dict]) -> tuple[list[dict], bool]:
    """Convenience function using module singleton."""
    return await _reranker.rerank(query, results)

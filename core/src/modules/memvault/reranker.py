"""Local cross-encoder reranking for memvault.

Uses Ollama nomic-embed-text with task-aware prefixes to re-score
search results. Includes circuit breaker for graceful degradation.
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
    weight_original: float = 0.4  # Weight of original score
    weight_rerank: float = 0.6  # Weight of rerank score
    timeout: float = 5.0  # Max seconds for reranking
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
    """Rerank search results using Ollama embedding model."""

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
        """Rerank results using cross-embedding similarity.

        Returns (reranked_results, was_applied).
        If reranking fails or circuit breaker is open, returns original results unchanged.
        """
        if not self.config.enabled or not self._breaker.is_available():
            return results, False

        if len(results) <= 1:
            return results, False

        try:
            from src.shared.embedding import get_embedding, get_embeddings_batch

            # Limit candidates
            candidates = results[: self.config.max_candidates]
            remainder = results[self.config.max_candidates :]

            # Get query embedding with search_query prefix
            query_emb = await get_embedding(f"search_query: {query}")
            if not query_emb:
                self._breaker.record_failure()
                return results, False

            # Batch re-embed candidates with search_document prefix
            snippets = [
                f"search_document: {r.get('content', '')[:self.config.snippet_length]}"
                for r in candidates
            ]
            doc_embeddings = await get_embeddings_batch(snippets)

            # Compute reranked scores
            from .scoring_pipeline import _cosine_similarity

            for i, r in enumerate(candidates):
                doc_emb = doc_embeddings[i] if i < len(doc_embeddings) else None
                if doc_emb:
                    rerank_score = max(_cosine_similarity(query_emb, doc_emb), 0.0)
                    # Weighted blend of original score and rerank score
                    r["score"] = (
                        self.config.weight_original * r["score"]
                        + self.config.weight_rerank * rerank_score
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

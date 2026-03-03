"""Memvault API client.

Usage:
    from workshop.clients.memvault import MemvaultClient

    client = MemvaultClient()
    results = client.recall("Python development preferences")
    profile = client.profile()
    client.extract("New memory", block_type="knowledge", tags=["python"])
"""

from ._base import BaseClient


class MemvaultClient(BaseClient):
    """Client for the Memvault memory system (Core API port 8801)."""

    def __init__(self, **kwargs):
        super().__init__(module="memvault", **kwargs)

    # ---- Read operations ----

    def recall(self, query: str, top_k: int = 5, min_score: float = 0.3) -> dict:
        """Semantic search over memory blocks. GET /search"""
        return self._get("/search", {"q": query, "top_k": top_k, "min_score": min_score})

    def stats(self) -> dict:
        """Aggregate memory statistics. GET /blocks + /tags + /profile"""
        return {
            "blocks": self._get("/blocks", {"page_size": 1}),
            "tags": self._get("/tags"),
            "profile": self._get("/profile"),
        }

    def profile(self, rebuild: bool = False) -> dict:
        """KAS profile scores. GET /profile"""
        params = {"rebuild": "true"} if rebuild else None
        return self._get("/profile", params)

    def cascade(self, query: str, top_k: int = 5) -> dict:
        """KG cascade recall (L2 Wisdom -> L1 Clusters -> L0 Triples -> Blocks). GET /kg/recall"""
        return self._get("/kg/recall", {"q": query, "top_k": top_k})

    def wisdom(self, confidence: str | None = None, tag: str | None = None) -> list:
        """List wisdom nodes. GET /kg/wisdom"""
        params: dict = {}
        if confidence:
            params["confidence"] = confidence
        if tag:
            params["tag"] = tag
        return self._get("/kg/wisdom", params or None)

    def attitudes(self, category: str | None = None) -> list:
        """List active attitude facts. GET /kg/attitudes"""
        return self._get("/kg/attitudes", {"category": category} if category else None)

    def skill_proficiency(self) -> list:
        """Skill proficiency ranking. GET /kg/skills/proficiency"""
        return self._get("/kg/skills/proficiency")

    # ---- Write operations ----

    def extract(
        self,
        content: str,
        block_type: str = "general",
        tags: list[str] | None = None,
        source_session: str | None = None,
    ) -> dict:
        """Create a new memory block. POST /blocks"""
        body: dict = {"content": content, "block_type": block_type, "tags": tags or []}
        if source_session:
            body["source_session"] = source_session
        return self._post("/blocks", body)

    def attitude_evolve(
        self, fact: str, category: str, source_session: str | None = None
    ) -> dict:
        """Evolve an attitude fact (ADD/UPDATE/NOOP). POST /kg/attitudes/evolve"""
        body: dict = {"fact": fact, "category": category}
        if source_session:
            body["source_session"] = source_session
        return self._post("/kg/attitudes/evolve", body)

    # ---- Convenience ----

    def health(self) -> bool:
        """Check API connectivity. Returns True if API responds."""
        try:
            self.profile()
            return True
        except Exception:
            return False

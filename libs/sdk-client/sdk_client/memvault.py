"""Memvault API client — full coverage of all Core API endpoints.

Usage:
    from sdk_client.memvault import MemvaultClient

    client = MemvaultClient()
    results = client.recall("Python development preferences")
    profile = client.profile()
    client.extract("New memory", block_type="knowledge", tags=["python"])
"""

from ._base import BaseClient


class MemvaultClient(BaseClient):
    """Client for the Memvault memory system (Core API port 10000)."""

    def __init__(self, **kwargs):
        super().__init__(module="memvault", **kwargs)

    # ======================== Blocks CRUD ========================

    def list_blocks(
        self,
        page: int = 1,
        page_size: int = 20,
        tag: str | None = None,
        tags: str | None = None,
        block_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        """List memory blocks with optional filters. GET /blocks"""
        params: dict = {"page": page, "page_size": page_size}
        if tag:
            params["tag"] = tag
        if tags:
            params["tags"] = tags
        if block_type:
            params["block_type"] = block_type
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return self._get("/blocks", params)

    def get_block(self, block_id: str) -> dict:
        """Get a single memory block by ID. GET /blocks/{id}"""
        return self._get(f"/blocks/{block_id}")

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

    def update_block(self, block_id: str, **fields) -> dict:
        """Update a memory block. PATCH /blocks/{id}

        Accepted fields: content, block_type, tags, source_session.
        """
        body = {k: v for k, v in fields.items() if v is not None}
        return self._put(f"/blocks/{block_id}", body)

    def delete_block(self, block_id: str) -> None:
        """Delete a memory block. DELETE /blocks/{id}"""
        self._delete(f"/blocks/{block_id}")

    # ======================== Search ========================

    def recall(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.3,
        include_metadata: bool = False,
        scope: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        """Semantic search over memory blocks. GET /search"""
        params: dict = {"q": query, "top_k": top_k, "min_score": min_score}
        if include_metadata:
            params["include_metadata"] = "true"
        if scope:
            params["scope"] = scope
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        return self._get("/search", params)

    def query_memory(
        self,
        query: str,
        task_mode: str = "auto",
        thinking_mode: str = "auto",
        load_budget: str = "standard",
        consumer: str = "human",
        top_k: int = 6,
    ) -> dict:
        """Unified fast/slow memory query. POST /query

        task_mode=auto infers intent from query content via classify_query().
        """
        return self._post(
            "/query",
            {
                "q": query,
                "task_mode": task_mode,
                "thinking_mode": thinking_mode,
                "load_budget": load_budget,
                "consumer": consumer,
                "top_k": top_k,
            },
        )

    def inject(
        self,
        query: str,
        task_mode: str = "build",
        thinking_mode: str = "auto",
        load_budget: str = "light",
        top_k: int = 6,
    ) -> dict:
        """Agent-facing fast memory payload. POST /inject"""
        return self._post(
            "/inject",
            {
                "q": query,
                "task_mode": task_mode,
                "thinking_mode": thinking_mode,
                "load_budget": load_budget,
                "consumer": "agent",
                "top_k": top_k,
            },
        )

    def inspect(
        self,
        query: str,
        task_mode: str = "reflect",
        load_budget: str = "deep",
        top_k: int = 6,
    ) -> dict:
        """Deep evidence inspection. POST /inspect"""
        return self._post(
            "/inspect",
            {
                "q": query,
                "task_mode": task_mode,
                "thinking_mode": "slow",
                "load_budget": load_budget,
                "consumer": "human",
                "top_k": top_k,
            },
        )

    # ======================== Sessions ========================

    def list_sessions(self, page: int = 1, page_size: int = 20) -> dict:
        """List sessions aggregated by source_session. GET /sessions"""
        return self._get("/sessions", {"page": page, "page_size": page_size})

    # ======================== Prefetch Metrics ========================

    def prefetch_metrics(self) -> dict:
        """Speculative prefetch cache metrics. GET /prefetch/metrics"""
        return self._get("/prefetch/metrics")

    # ======================== Tags ========================

    def list_tags(self) -> list:
        """List all tags with counts. GET /tags"""
        return self._get("/tags")

    def sync_tags(self) -> dict:
        """Sync tag counts from blocks. POST /tags/sync"""
        return self._post("/tags/sync")

    # ======================== Knowledge Domains ========================

    def list_domains(self, page: int = 1, page_size: int = 20) -> dict:
        """List knowledge domains. GET /domains"""
        return self._get("/domains", {"page": page, "page_size": page_size})

    def create_domain(self, name: str, description: str | None = None) -> dict:
        """Create a knowledge domain. POST /domains"""
        body: dict = {"name": name}
        if description:
            body["description"] = description
        return self._post("/domains", body)

    def update_domain(self, domain_id: str, **fields) -> dict:
        """Update a knowledge domain. PATCH /domains/{id}"""
        body = {k: v for k, v in fields.items() if v is not None}
        return self._patch(f"/domains/{domain_id}", body)

    # ======================== Profile ========================

    def profile(self, rebuild: bool = False) -> dict:
        """KAS profile scores. GET /profile"""
        params = {"rebuild": "true"} if rebuild else None
        return self._get("/profile", params)

    def upsert_profile(
        self,
        knowledge_score: float | None = None,
        attitude_score: float | None = None,
    ) -> dict:
        """Upsert profile scores. PUT /profile"""
        body: dict = {}
        if knowledge_score is not None:
            body["knowledge_score"] = knowledge_score
        if attitude_score is not None:
            body["attitude_score"] = attitude_score
        return self._put("/profile", body)

    def recalculate_profile(self) -> dict:
        """Recalculate KAS scores from actual KG data. POST /profile/recalculate"""
        return self._post("/profile/recalculate")

    # ======================== Sync ========================

    def sync_stats(self) -> dict:
        """Get sync/extraction statistics. GET /sync/stats"""
        return self._get("/sync/stats")

    # ======================== Sync — Scan ========================

    def sync_scan(self) -> dict:
        """Trigger a sync scan for new memories. POST /sync/scan"""
        return self._post("/sync/scan")

    # ======================== Status ========================

    def status(self) -> dict:
        """Module status check. GET /status"""
        return self._get("/status")

    # ======================== Frozen Tier ========================

    def list_frozen(
        self,
        page: int = 1,
        page_size: int = 20,
        block_type: str | None = None,
        tag: str | None = None,
    ) -> dict:
        """List frozen block metadata. GET /frozen"""
        params: dict = {"page": page, "page_size": page_size}
        if block_type:
            params["block_type"] = block_type
        if tag:
            params["tag"] = tag
        return self._get("/frozen", params)

    def thaw_frozen(self, block_id: str) -> dict:
        """Thaw a frozen block (fetch content from S3). GET /frozen/{id}/thaw"""
        return self._get(f"/frozen/{block_id}/thaw")

    # ======================== KG — Triples ========================

    def create_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float | None = None,
        source_session: str | None = None,
    ) -> dict:
        """Create a KG triple. POST /kg/triples"""
        body: dict = {"subject": subject, "predicate": predicate, "object": obj}
        if confidence is not None:
            body["confidence"] = confidence
        if source_session:
            body["source_session"] = source_session
        return self._post("/kg/triples", body)

    def batch_ingest_triples(self, triples: list[dict], session_id: str | None = None) -> dict:
        """Batch ingest KG triples. POST /kg/triples/batch"""
        body: dict = {"triples": triples}
        if session_id:
            body["session_id"] = session_id
        return self._post("/kg/triples/batch", body)

    def list_triples(
        self,
        predicate: str | None = None,
        subject: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List KG triples with optional filters. GET /kg/triples"""
        params: dict = {"page": page, "page_size": page_size}
        if predicate:
            params["predicate"] = predicate
        if subject:
            params["subject"] = subject
        return self._get("/kg/triples", params)

    def search_triples(self, query: str, top_k: int = 10) -> list:
        """Semantic search over KG triples. GET /kg/triples/search"""
        return self._get("/kg/triples/search", {"q": query, "top_k": top_k})

    def delete_triple(self, triple_id: str) -> None:
        """Delete a KG triple. DELETE /kg/triples/{id}"""
        self._delete(f"/kg/triples/{triple_id}")

    def update_triple(
        self, triple_id: str, subject: str, predicate: str, obj: str, **fields
    ) -> dict:
        """Update a KG triple. PUT /kg/triples/{id}"""
        body: dict = {"subject": subject, "predicate": predicate, "object": obj}
        body.update({k: v for k, v in fields.items() if v is not None})
        return self._put(f"/kg/triples/{triple_id}", body)

    def invalidate_triple(
        self,
        triple_id: str,
        reason: str = "manual",
        replacement_id: str | None = None,
    ) -> dict:
        """Invalidate a KG triple (soft temporal invalidation). PUT /kg/triples/{id}/invalidate"""
        body: dict = {"reason": reason}
        if replacement_id:
            body["replacement_triple_id"] = replacement_id
        return self._put(f"/kg/triples/{triple_id}/invalidate", body)

    # ======================== KG — Entity Resolution ========================

    def list_entities(
        self,
        entity_type: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """List canonical entities. GET /kg/entities"""
        params: dict = {"page": page, "page_size": page_size}
        if entity_type:
            params["entity_type"] = entity_type
        return self._get("/kg/entities", params)

    def entity_stats(self) -> dict:
        """Entity resolution statistics. GET /kg/entities/stats"""
        return self._get("/kg/entities/stats")

    def entity_merge_candidates(self, threshold: float = 0.92, limit: int = 50) -> list:
        """Find entities that are merge candidates. GET /kg/entities/merge-candidates"""
        return self._get("/kg/entities/merge-candidates", {"threshold": threshold, "limit": limit})

    def merge_entities(self, primary_id: str, secondary_id: str) -> dict:
        """Merge secondary entity into primary. POST /kg/entities/merge"""
        body = {"primary_id": primary_id, "secondary_id": secondary_id}
        return self._post("/kg/entities/merge", body)

    def backfill_entity_resolution(self) -> dict:
        """Backfill entity resolution for unresolved triples. POST /kg/entities/backfill"""
        return self._post("/kg/entities/backfill", timeout=120)

    # ======================== KG — Entity Auto-Merge ========================

    def auto_merge_entities(
        self,
        threshold: float = 0.92,
        max_merges: int = 50,
    ) -> dict:
        """Auto-merge entities above similarity threshold. POST /kg/entities/auto-merge"""
        return self._post(
            "/kg/entities/auto-merge",
            params={"threshold": threshold, "max_merges": max_merges},
        )

    # ======================== KG — Graph Traversal ========================

    def graph_traverse(
        self,
        entity: str,
        max_depth: int = 2,
        direction: str = "both",
        predicates: str | None = None,
        max_results: int = 200,
    ) -> dict:
        """Multi-hop graph traversal from a seed entity. GET /kg/traverse"""
        params: dict = {
            "entity": entity,
            "max_depth": max_depth,
            "direction": direction,
            "max_results": max_results,
        }
        if predicates:
            params["predicates"] = predicates
        return self._get("/kg/traverse", params)

    # ======================== KG — Communities ========================

    def list_communities(self, resolution_level: int | None = None) -> list:
        """List KG communities. GET /kg/communities"""
        params: dict = {}
        if resolution_level is not None:
            params["resolution_level"] = resolution_level
        return self._get("/kg/communities", params or None)

    def get_community(self, community_id: str) -> dict:
        """Get community detail with members. GET /kg/communities/{id}"""
        return self._get(f"/kg/communities/{community_id}")

    def regenerate_communities(self, communities: list[dict], generated_at: str) -> dict:
        """Save regenerated community data. POST /kg/communities/regenerate"""
        body = {"communities": communities, "generated_at": generated_at}
        return self._post("/kg/communities/regenerate", body)

    def update_community_description(self, community_id: str, description_zh: str) -> dict:
        """Update community description. POST /kg/communities/{id}/description"""
        return self._post(
            f"/kg/communities/{community_id}/description", {"description_zh": description_zh}
        )

    # ======================== KG — Community Summaries ========================

    def list_summaries(self, resolution_level: int | None = None, tag: str | None = None) -> list:
        """List community summaries. GET /kg/summaries"""
        params: dict = {}
        if resolution_level is not None:
            params["resolution_level"] = resolution_level
        if tag:
            params["tag"] = tag
        return self._get("/kg/summaries", params or None)

    def regenerate_summaries(self, summaries: list[dict], generated_at: str) -> dict:
        """Save regenerated community summary data. POST /kg/summaries/regenerate"""
        body = {"summaries": summaries, "generated_at": generated_at}
        return self._post("/kg/summaries/regenerate", body)

    # ======================== KG — Cascade Recall ========================

    def cascade(
        self,
        query: str,
        top_k: int = 5,
        skip_routing: bool = False,
        evaluate: str = "default",
    ) -> dict:
        """KG cascade recall (L2→L1→L0→Blocks). GET /kg/recall"""
        params: dict = {"q": query, "top_k": top_k}
        if skip_routing:
            params["skip_routing"] = "true"
        if evaluate != "default":
            params["evaluate"] = evaluate
        return self._get("/kg/recall", params)

    # ======================== KG — Maintenance ========================

    def lint(
        self,
        checks: str = "all",
        fix: bool = False,
        dry_run: bool = True,
    ) -> dict:
        """Run knowledge lint checks. POST /kg/lint"""
        params: dict = {
            "checks": checks,
            "fix": str(fix).lower(),
            "dry_run": str(dry_run).lower(),
        }
        return self._post("/kg/lint", params=params, timeout=120)

    def backfill_embeddings(self, batch_size: int = 50) -> dict:
        """Backfill missing embeddings for triples and attitudes. POST /kg/embeddings/backfill"""
        return self._post("/kg/embeddings/backfill", params={"batch_size": batch_size}, timeout=120)

    # ======================== KG — Session Context (Flywheel) ========================

    def session_context(self, source_session: str, space_id: str = "default") -> dict:
        """Get blocks + triples + entities for a session. GET /kg/session-context"""
        return self._get(
            "/kg/session-context",
            {"source_session": source_session, "space_id": space_id},
        )

    # ======================== KG — Intelligence Ingest (Flywheel) ========================

    def intelligence_ingest(
        self,
        content: str,
        space_id: str = "default",
        digest_type: str = "weekly",
        period: str = "",
    ) -> dict:
        """Publish intelligence digest into memvault. POST /kg/intelligence/ingest"""
        return self._post(
            "/kg/intelligence/ingest",
            params={
                "space_id": space_id,
                "digest_type": digest_type,
                "period": period,
                "content": content,
            },
        )

    # ======================== KG — Interest Profile ========================

    def generate_interest(self) -> dict:
        """Generate daily interest snapshot from query journal. POST /kg/interest/generate"""
        return self._post("/kg/interest/generate")

    def get_attention(self) -> dict:
        """Get attention profile (active/fading/historical entities). GET /kg/interest/attention"""
        return self._get("/kg/interest/attention")

    def get_knowledge_gaps(self, days: int = 7, limit: int = 20) -> list:
        """Recurring queries with low-quality results. GET /kg/interest/gaps"""
        return self._get("/kg/interest/gaps", {"days": days, "limit": limit})

    # ======================== Search Feedback ========================

    def feedback(
        self,
        entity_id: str,
        query: str,
        signal: str = "positive",
        feedback_source: str = "agent",
    ) -> dict:
        """Record explicit relevance feedback for a search result. POST /feedback"""
        return self._post(
            "/feedback",
            {
                "entity_id": entity_id,
                "query": query,
                "signal": signal,
                "feedback_source": feedback_source,
            },
        )

    def get_feedback(self, entity_id: str) -> dict:
        """Get aggregated feedback for a block. GET /feedback/{id}"""
        return self._get(f"/feedback/{entity_id}")

    # ======================== Convenience ========================

    def stats(self) -> dict:
        """Aggregate memory statistics. GET /blocks + /tags + /profile"""
        return {
            "blocks": self._get("/blocks", {"page_size": 1}),
            "tags": self._get("/tags"),
            "profile": self._get("/profile"),
        }

    def dream(
        self,
        dry_run: bool = True,
        force: bool = False,
    ) -> dict:
        """Run dream consolidation. POST /dream"""
        params: dict = {
            "dry_run": str(dry_run).lower(),
            "force": str(force).lower(),
        }
        return self._post("/dream", params=params, timeout=180)

    # ======================== Entity Edges (Multi-Signal) ========================

    def list_entity_edges(
        self,
        min_weight: float = 0.1,
        limit: int = 500,
        space_id: str = "default",
    ) -> list[dict]:
        """List weighted entity edges above min_weight threshold."""
        return self._get(
            "/kg/entity-edges",
            params={"space_id": space_id, "min_weight": min_weight, "limit": limit},
        )

    def recompute_edge_weights(self, space_id: str = "default") -> dict:
        """Trigger full edge weight recomputation via Edge Pipeline."""
        return self._post(
            "/kg/entity-edges/recompute",
            params={"space_id": space_id},
            timeout=120,
        )

    def surprise_connections(
        self,
        strategy: str | None = None,
        limit: int = 10,
        space_id: str = "default",
    ) -> list[dict]:
        """Discover unexpected knowledge connections."""
        params: dict = {"space_id": space_id, "limit": limit}
        if strategy:
            params["strategy"] = strategy
        return self._get("/kg/entity-edges/surprises", params=params)

    # ======================== Review Queue ========================

    def list_review_queue(
        self,
        page: int = 1,
        page_size: int = 20,
        space_id: str = "default",
    ) -> dict:
        """List pending review items."""
        return self._get(
            "/review-queue",
            params={"space_id": space_id, "page": page, "page_size": page_size},
        )

    def review_approve(self, item_id: str) -> dict:
        """Approve a pending review item."""
        return self._post(f"/review-queue/{item_id}/approve")

    def review_reject(self, item_id: str) -> dict:
        """Reject a pending review item."""
        return self._post(f"/review-queue/{item_id}/reject")

    def review_defer(self, item_id: str) -> dict:
        """Defer a review item."""
        return self._post(f"/review-queue/{item_id}/defer")

    # ======================== Frontier (Worker 1) ========================

    def frontier_top(self, n: int = 5, space_id: str | None = None) -> dict:
        """Get top-N frontier candidates. GET /frontier/top

        Returns a FrontierTopResponse: {space_id, n, items: [...]}
        """
        params: dict = {"n": n}
        if space_id:
            params["space_id"] = space_id
        return self._get("/frontier/top", params)

    # ======================== Health ========================

    def health(self) -> bool:
        """Check API connectivity. Returns True if API responds."""
        try:
            self.profile()
            return True
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("health check failed: %s", e)
            return False

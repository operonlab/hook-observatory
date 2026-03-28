"""Intelflow API client — full coverage of Core API endpoints.

Covers: Reports, Search, Topics, Dashboard, Frozen Tier.

Note: Briefing-related methods have been moved to BriefingClient.
    from sdk_client.briefing import BriefingClient

Usage:
    from sdk_client.intelflow import IntelflowClient

    client = IntelflowClient()
    reports = client.list_reports()
    results = client.semantic_search("AI agent frameworks")
    graph = client.get_topic_graph()
"""

from ._base import BaseClient


class IntelflowClient(BaseClient):
    """Client for the Intelflow intelligence system (Core API port 10000)."""

    def __init__(self, **kwargs):
        super().__init__(module="intelflow", **kwargs)

    # ======================== Reports ========================

    def list_reports(
        self,
        page: int = 1,
        page_size: int = 20,
        tag: str | None = None,
        tags: str | None = None,
        topic_id: str | None = None,
    ) -> dict:
        """List reports with optional filters. GET /reports"""
        params: dict = {"page": page, "page_size": page_size}
        if tag:
            params["tag"] = tag
        if tags:
            params["tags"] = tags
        if topic_id:
            params["topic_id"] = topic_id
        return self._get("/reports", params)

    def get_report(self, report_id: str) -> dict:
        """Get a single report by ID. GET /reports/{id}"""
        return self._get(f"/reports/{report_id}")

    def create_report(
        self,
        title: str,
        query: str,
        content: str,
        sources: list[dict] | None = None,
        tags: list[str] | None = None,
        skill_name: str | None = None,
        created_at: str | None = None,
    ) -> dict:
        """Create a new report. POST /reports"""
        body: dict = {
            "title": title,
            "query": query,
            "content": content,
            "sources": sources or [],
            "tags": tags or [],
        }
        if skill_name:
            body["skill_name"] = skill_name
        if created_at:
            body["created_at"] = created_at
        return self._post("/reports", body)

    def update_report(self, report_id: str, **fields) -> dict:
        """Update a report. PUT /reports/{id}

        Accepted fields: title, query, content, sources, tags, skill_name.
        """
        body = {k: v for k, v in fields.items() if v is not None}
        return self._put(f"/reports/{report_id}", body)

    def delete_report(self, report_id: str) -> None:
        """Delete a report. DELETE /reports/{id}"""
        self._delete(f"/reports/{report_id}")

    # ======================== Search ========================

    def semantic_search(
        self,
        query: str,
        limit: int = 5,
        threshold: float | None = None,
    ) -> list:
        """Semantic search over reports. POST /search"""
        body: dict = {"query": query, "limit": limit}
        if threshold is not None:
            body["threshold"] = threshold
        return self._post("/search", body)

    def check_duplicate(
        self,
        query: str,
        threshold: float | None = None,
    ) -> dict:
        """Check for duplicate reports before saving. POST /search/check"""
        body: dict = {"query": query}
        if threshold is not None:
            body["threshold"] = threshold
        return self._post("/search/check", body)

    # ======================== Topics ========================

    def list_topics(
        self,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """List topics. GET /topics"""
        return self._get("/topics", {"page": page, "page_size": page_size})

    def create_topic(self, name: str, **fields) -> dict:
        """Create a topic. POST /topics"""
        body: dict = {"name": name}
        body.update({k: v for k, v in fields.items() if v is not None})
        return self._post("/topics", body)

    def get_related_topics(self, topic_id: str) -> list:
        """Get related topics. GET /topics/{id}/related"""
        return self._get(f"/topics/{topic_id}/related")

    def backfill_topics(self) -> dict:
        """Backfill topics from existing report tags. POST /topics/backfill"""
        return self._post("/topics/backfill")

    def get_topic_graph(self) -> dict:
        """Get topic relationship graph. GET /topics/graph"""
        return self._get("/topics/graph")

    # ======================== Dashboard ========================

    def get_dashboard(self) -> dict:
        """Get dashboard summary. GET /dashboard"""
        return self._get("/dashboard")

    def get_timeline(self, days: int = 30) -> dict:
        """Get report timeline. GET /dashboard/timeline"""
        return self._get("/dashboard/timeline", {"days": days})

    # ======================== Status ========================

    def status(self) -> dict:
        """Module status check. GET /status"""
        return self._get("/status")

    # ======================== Frozen Tier ========================

    def list_frozen_reports(
        self,
        tag: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List frozen report metadata. GET /frozen/reports"""
        params: dict = {"page": page, "page_size": page_size}
        if tag:
            params["tag"] = tag
        return self._get("/frozen/reports", params)

    def thaw_report(self, report_id: str) -> dict:
        """Thaw a frozen report (fetch from S3). GET /frozen/reports/{id}/thaw"""
        return self._get(f"/frozen/reports/{report_id}/thaw")

    def list_frozen_briefings(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List frozen briefing metadata. GET /frozen/briefings"""
        return self._get("/frozen/briefings", {"page": page, "page_size": page_size})

    def thaw_briefing(self, briefing_id: str) -> dict:
        """Thaw a frozen briefing (fetch from S3). GET /frozen/briefings/{id}/thaw"""
        return self._get(f"/frozen/briefings/{briefing_id}/thaw")

    # ======================== Convenience ========================

    def search_reports(self, query: str, limit: int = 5) -> list:
        """Alias for semantic_search — matches CLI naming."""
        return self.semantic_search(query, limit=limit)

    def health(self) -> bool:
        """Check API connectivity. Returns True if API responds."""
        try:
            self.status()
            return True
        except Exception:
            return False

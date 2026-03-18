"""Briefing API client — full coverage of Core API endpoints.

Covers: Topics, Subtopics, Analysts, Daily Briefings, Entries, Follow-Ups, Frozen.

Usage:
    from workshop.clients.briefing import BriefingClient

    client = BriefingClient()
    topics = client.list_topics()
    briefings = client.list_briefings()
    today = client.get_briefings_by_date("2026-03-18")
"""

from ._base import BaseClient


class BriefingClient(BaseClient):
    """Client for the Briefing intelligence module (Core API port 8801)."""

    def __init__(self, **kwargs):
        super().__init__(module="briefing", **kwargs)

    # ======================== Topics ========================

    def list_topics(
        self,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        """List briefing topics. GET /topics"""
        return self._get("/topics", {"page": page, "page_size": page_size})

    def create_topic(self, name: str, **fields) -> dict:
        """Create a briefing topic. POST /topics"""
        body: dict = {"name": name}
        body.update({k: v for k, v in fields.items() if v is not None})
        return self._post("/topics", body)

    def update_topic(self, topic_id: str, **fields) -> dict:
        """Update a briefing topic. PUT /topics/{id}"""
        body = {k: v for k, v in fields.items() if v is not None}
        return self._put(f"/topics/{topic_id}", body)

    def delete_topic(self, topic_id: str) -> None:
        """Delete a briefing topic. DELETE /topics/{id}"""
        self._delete(f"/topics/{topic_id}")

    def toggle_topic(self, topic_id: str) -> dict:
        """Toggle a briefing topic on/off. PATCH /topics/{id}/toggle"""
        return self._patch(f"/topics/{topic_id}/toggle")

    # ======================== Subtopics ========================

    def add_subtopic(self, topic_id: str, name: str, **fields) -> dict:
        """Add a subtopic. POST /topics/{id}/subtopics"""
        body: dict = {"name": name}
        body.update({k: v for k, v in fields.items() if v is not None})
        return self._post(f"/topics/{topic_id}/subtopics", body)

    def update_subtopic(self, topic_id: str, subtopic_id: str, **fields) -> dict:
        """Update a subtopic. PUT /topics/{id}/subtopics/{sid}"""
        body = {k: v for k, v in fields.items() if v is not None}
        return self._put(f"/topics/{topic_id}/subtopics/{subtopic_id}", body)

    def delete_subtopic(self, topic_id: str, subtopic_id: str) -> None:
        """Delete a subtopic. DELETE /topics/{id}/subtopics/{sid}"""
        self._delete(f"/topics/{topic_id}/subtopics/{subtopic_id}")

    # ======================== Analysts ========================

    def list_analysts(self) -> list:
        """List analysts. GET /analysts"""
        return self._get("/analysts")

    def create_analyst(self, name: str, **fields) -> dict:
        """Create an analyst. POST /analysts"""
        body: dict = {"name": name}
        body.update({k: v for k, v in fields.items() if v is not None})
        return self._post("/analysts", body)

    def update_analyst(self, analyst_id: str, **fields) -> dict:
        """Update an analyst. PUT /analysts/{id}"""
        body = {k: v for k, v in fields.items() if v is not None}
        return self._put(f"/analysts/{analyst_id}", body)

    def delete_analyst(self, analyst_id: str) -> None:
        """Delete an analyst. DELETE /analysts/{id}"""
        self._delete(f"/analysts/{analyst_id}")

    def toggle_analyst(self, analyst_id: str) -> dict:
        """Toggle an analyst on/off. PATCH /analysts/{id}/toggle"""
        return self._patch(f"/analysts/{analyst_id}/toggle")

    # ======================== Daily Briefings ========================

    def list_briefings(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        topic_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List daily briefings. GET /daily"""
        params: dict = {"page": page, "page_size": page_size}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if topic_id:
            params["topic_id"] = topic_id
        return self._get("/daily", params)

    def get_briefings_by_date(self, target_date: str) -> list:
        """Get briefings for a specific date. GET /daily/{date}"""
        return self._get(f"/daily/{target_date}")

    def get_daily_summary(self, target_date: str) -> dict:
        """Get daily summary for a date. GET /daily/{date}/summary"""
        return self._get(f"/daily/{target_date}/summary")

    def get_briefing_by_domain(self, target_date: str, domain: str) -> dict:
        """Get a specific briefing by date and domain. GET /daily/{date}/{domain}"""
        return self._get(f"/daily/{target_date}/{domain}")

    def create_briefing(self, **fields) -> dict:
        """Create a briefing. POST /daily"""
        body = {k: v for k, v in fields.items() if v is not None}
        return self._post("/daily", body)

    def update_briefing(self, briefing_id: str, **fields) -> dict:
        """Update briefing status. PATCH /daily/{id}"""
        body = {k: v for k, v in fields.items() if v is not None}
        return self._patch(f"/daily/{briefing_id}", body)

    # ======================== Entries ========================

    def list_entries(self, briefing_id: str, phase: str | None = None) -> list:
        """List entries for a briefing. GET /daily/{briefing_id}/entries"""
        params: dict = {}
        if phase:
            params["phase"] = phase
        return self._get(f"/daily/{briefing_id}/entries", params)

    def add_entry(self, briefing_id: str, **fields) -> dict:
        """Add an entry to a briefing. POST /daily/{briefing_id}/entries"""
        body = {k: v for k, v in fields.items() if v is not None}
        return self._post(f"/daily/{briefing_id}/entries", body)

    # ======================== Follow-Ups ========================

    def list_follow_ups(self, briefing_id: str) -> list:
        """List follow-ups for a briefing. GET /daily/{briefing_id}/follow-ups"""
        return self._get(f"/daily/{briefing_id}/follow-ups")

    def create_follow_up(self, briefing_id: str, **fields) -> dict:
        """Create a follow-up for a briefing. POST /daily/{briefing_id}/follow-ups"""
        body = {k: v for k, v in fields.items() if v is not None}
        return self._post(f"/daily/{briefing_id}/follow-ups", body)

    # ======================== Frozen ========================

    def list_frozen_briefings(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> list:
        """List frozen briefing metadata. GET /frozen"""
        return self._get("/frozen", {"page": page, "page_size": page_size})

    def thaw_briefing(self, briefing_id: str) -> dict:
        """Thaw a frozen briefing (fetch from S3). GET /frozen/{id}/thaw"""
        return self._get(f"/frozen/{briefing_id}/thaw")

    # ======================== Status ========================

    def status(self) -> dict:
        """Module status check. GET /status"""
        return self._get("/status")

    def health(self) -> bool:
        """Check API connectivity. Returns True if API responds."""
        try:
            self.status()
            return True
        except Exception:
            return False

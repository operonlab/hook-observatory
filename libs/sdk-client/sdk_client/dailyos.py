"""DailyOS API client — Core module at /api/dailyos.

Wraps methods CRUD, method selection config, strategy preview, and daily plans.

Usage:
    from sdk_client.dailyos import DailyOSClient

    client = DailyOSClient()
    methods = client.list_methods()
    today = client.get_today()
"""

from typing import Any

from ._base import APIError, BaseClient

DailyOSError = APIError


class DailyOSClient(BaseClient):
    """HTTP client for the DailyOS Core API module.

    Args:
        base_url: Core API URL. Defaults to CORE_API_URL env or localhost:10000.
        space_id: Space ID. Defaults to WORKSHOP_SPACE_ID env or "default".
        timeout: Default request timeout in seconds.
    """

    def __init__(self, **kwargs: Any):
        super().__init__(module="dailyos", **kwargs)

    # ======================== Methods CRUD ========================

    def list_methods(
        self,
        include_presets: bool = True,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List all methods including optional presets. GET /methods"""
        return self._get(
            "/methods",
            {"include_presets": include_presets, "page": page, "page_size": page_size},
        )

    def get_method(self, method_id: str) -> dict:
        """Get method by ID. GET /methods/{method_id}"""
        return self._get(f"/methods/{method_id}")

    def create_method(self, data: dict) -> dict:
        """Create a new method. POST /methods

        data keys:
            slug (str): URL-friendly identifier.
            name (str): Method display name.
            name_zh (str, optional): Chinese display name.
            description (str, optional): Method description.
            icon (str, optional): Icon identifier.
            color (str, optional): Hex color code.
            config (dict, optional): Method-specific configuration.
            layout_type (str, optional): Layout type identifier.
            tags (list[str], optional): Tag list.
        """
        return self._post("/methods", data)

    def update_method(self, method_id: str, data: dict) -> dict:
        """Update an existing method. PUT /methods/{method_id}"""
        return self._put(f"/methods/{method_id}", data)

    def delete_method(self, method_id: str) -> None:
        """Delete a method. DELETE /methods/{method_id}"""
        return self._delete(f"/methods/{method_id}")

    def clone_method(self, method_id: str) -> dict:
        """Clone a method into the current space. POST /methods/{method_id}/clone"""
        return self._post(f"/methods/{method_id}/clone")

    # ======================== Config (Method Selection) ========================

    def get_active_methods(self, context: str = "default") -> list:
        """List active method selections for a context. GET /config/method"""
        return self._get("/config/method", {"context": context})

    def activate_method(
        self,
        method_id: str,
        context: str = "default",
        overrides: dict | None = None,
    ) -> dict:
        """Activate a method for a context. POST /config/method/activate

        Args:
            method_id: Method UUID to activate.
            context: Context key, default "default".
            overrides: Optional config overrides for this selection.
        """
        body: dict[str, Any] = {"method_id": method_id, "context": context}
        if overrides is not None:
            body["overrides"] = overrides
        return self._post("/config/method/activate", body)

    def deactivate_method(self, selection_id: str) -> None:
        """Remove a method selection. DELETE /config/method/{selection_id}"""
        return self._delete(f"/config/method/{selection_id}")

    def get_guide(self, context: str = "default") -> dict:
        """Get composite guide for active methods in context. GET /config/guide

        Returns:
            dict with keys: guide (str), method_count (int), method_names (list).
        """
        return self._get("/config/guide", {"context": context})

    def get_method_history(
        self,
        context: str = "default",
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List method activation history for a context. GET /config/method/history"""
        return self._get(
            "/config/method/history",
            {"context": context, "page": page, "page_size": page_size},
        )

    # ======================== Strategy Preview ========================

    def preview_method(self, method_id: str) -> dict:
        """Preview a method's strategy output. POST /methods/{method_id}/preview"""
        return self._post(f"/methods/{method_id}/preview")

    # ======================== Daily Plans ========================

    def list_plans(
        self,
        page: int = 1,
        page_size: int = 20,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        """List daily plans with optional date range. GET /plans

        Args:
            date_from: ISO-8601 date string (inclusive).
            date_to: ISO-8601 date string (inclusive).
        """
        return self._get(
            "/plans",
            {
                "page": page,
                "page_size": page_size,
                "date_from": date_from,
                "date_to": date_to,
            },
        )

    def get_today(self, context: str = "default") -> dict:
        """Get or create today's daily plan. GET /plans/today"""
        return self._get("/plans/today", {"context": context})

    def get_plan(self, plan_id: str) -> dict:
        """Get a daily plan by ID. GET /plans/{plan_id}"""
        return self._get(f"/plans/{plan_id}")

    def update_plan(self, plan_id: str, data: dict) -> dict:
        """Update a daily plan. PUT /plans/{plan_id}

        data keys:
            items (list, optional): Plan item list.
            method_state (dict, optional): Per-method runtime state.
            reflection (str, optional): End-of-day reflection text.
            completion_score (float, optional): Completion score 0-100.
        """
        return self._put(f"/plans/{plan_id}", data)

    def transition_plan(self, plan_id: str, status: str, comment: str | None = None) -> dict:
        """Transition a plan to a new status. POST /plans/{plan_id}/transition

        Args:
            plan_id: Plan UUID.
            status: Target status (e.g. "active", "completed", "skipped").
            comment: Optional transition comment.
        """
        body: dict[str, Any] = {"status": status}
        if comment is not None:
            body["comment"] = comment
        return self._post(f"/plans/{plan_id}/transition", body)

    # ======================== Activity Spans ========================

    def list_spans(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list:
        """List activity spans, optionally filtered by date range. GET /spans"""
        return self._get(
            "/spans",
            {"date_from": date_from, "date_to": date_to},
        )

    def create_span(self, data: dict) -> dict:
        """Create a new activity span. POST /spans

        data keys:
            title (str): Span title.
            start_date (str): Start date (YYYY-MM-DD, inclusive).
            end_date (str): End date (YYYY-MM-DD, inclusive).
            category (str, optional): Category label.
            color (str, optional): Hex color code.
            notes (str, optional): Free-form notes.
        """
        return self._post("/spans", data)

    def update_span(self, span_id: str, data: dict) -> dict:
        """Update an activity span. PUT /spans/{span_id}"""
        return self._put(f"/spans/{span_id}", data)

    def delete_span(self, span_id: str) -> None:
        """Delete an activity span. DELETE /spans/{span_id}"""
        return self._delete(f"/spans/{span_id}")

    def get_spans_for_date(self, target_date: str) -> list:
        """Get active spans covering a date. GET /spans/for-date/{target_date}"""
        return self._get(f"/spans/for-date/{target_date}")

    def get_spans_for_range(self, range_start: str, range_end: str) -> list:
        """Get active spans overlapping a range. GET /spans/for-range"""
        return self._get(
            "/spans/for-range",
            {"range_start": range_start, "range_end": range_end},
        )

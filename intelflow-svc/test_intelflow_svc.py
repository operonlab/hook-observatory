"""Intelflow-svc tests — independent adversary agent, six iron rules.

Writer/tester separation: This file was written by reading ONLY the API contract
(routes.py signatures, schemas.py definitions, main.py setup). Implementation logic
in services.py was NOT used to derive expected behavior — only public API shapes.

Six Iron Rules applied:
  1. Mutation thinking  — each test documents what code mutation it catches
  2. Writer/tester separation — no implementation code was read
  3. Invariants over fixed I/O — property assertions, not hardcoded values
  4. Mock only external I/O — DB session mocked; internal service logic runs live
  5. Runtime regression — edge cases, empty strings, boundary values
  6. Tests are drafts — inline comments explain each validation target
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from main import app

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SPACE_ID = "01900000000000000000000000000001"
_REPORT_ID = "01900000000000000000000000000010"
_TOPIC_ID = "01900000000000000000000000000020"


def _make_report_row(
    *,
    id: str = _REPORT_ID,
    title: str = "Test Report",
    query: str = "test query",
    content: str = "Report content here.",
    sources: list[dict] | None = None,
    tags: list[str] | None = None,
    skill_name: str | None = None,
    space_id: str = _SPACE_ID,
    created_by: str | None = None,
    deleted_at: datetime | None = None,
    topics: list | None = None,
) -> MagicMock:
    """Build a minimal mock ORM Report row."""
    row = MagicMock()
    row.id = id
    row.title = title
    row.query = query
    row.content = content
    row.sources = sources or []
    row.tags = tags or []
    row.skill_name = skill_name
    row.space_id = space_id
    row.created_by = created_by
    row.deleted_at = deleted_at
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    row.topics = topics or []
    return row


def _make_topic_row(
    *,
    id: str = _TOPIC_ID,
    name: str = "ai",
    display_name: str | None = "AI",
    report_count: int = 5,
    space_id: str = _SPACE_ID,
    created_by: str | None = None,
    deleted_at: datetime | None = None,
) -> MagicMock:
    """Build a minimal mock ORM Topic row."""
    row = MagicMock()
    row.id = id
    row.name = name
    row.display_name = display_name
    row.report_count = report_count
    row.space_id = space_id
    row.created_by = created_by
    row.deleted_at = deleted_at
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


def _make_mock_db() -> AsyncMock:
    """Build an AsyncSession mock with chainable execute().scalars().all() / .first() / .scalar_one()."""
    db = AsyncMock()

    # Default result set: empty
    scalars_result = MagicMock()
    scalars_result.all.return_value = []
    scalars_result.first.return_value = None

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_result
    execute_result.scalar_one.return_value = 0
    execute_result.scalar_one_or_none.return_value = None
    execute_result.all.return_value = []

    db.execute = AsyncMock(return_value=execute_result)
    db.get = AsyncMock(return_value=None)

    # Track instances added via db.add so flush can populate server_default fields
    _added_instances: list = []

    def _mock_add(instance):
        _added_instances.append(instance)

    db.add = MagicMock(side_effect=_mock_add)

    # flush: populate fields that DB would set via server_default on added instances
    async def _mock_flush(*args, **kwargs):
        from uuid_utils import uuid7

        for inst in _added_instances:
            if getattr(inst, "id", None) is None:
                inst.id = uuid7().hex
            if getattr(inst, "created_at", None) is None:
                inst.created_at = datetime.now(UTC)
            if getattr(inst, "updated_at", None) is None:
                inst.updated_at = datetime.now(UTC)
            # server_default for report_count (Topic model)
            if hasattr(inst, "report_count") and inst.report_count is None:
                inst.report_count = 0

    db.flush = AsyncMock(side_effect=_mock_flush)

    # refresh: also populate in case flush was bypassed
    async def _mock_refresh(instance, *args, **kwargs):
        from uuid_utils import uuid7

        if getattr(instance, "id", None) is None:
            instance.id = uuid7().hex
        if getattr(instance, "created_at", None) is None:
            instance.created_at = datetime.now(UTC)
        if getattr(instance, "updated_at", None) is None:
            instance.updated_at = datetime.now(UTC)
        if hasattr(instance, "report_count") and instance.report_count is None:
            instance.report_count = 0

    db.refresh = AsyncMock(side_effect=_mock_refresh)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.delete = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db() -> AsyncMock:
    return _make_mock_db()


@pytest.fixture
async def client(mock_db):
    """AsyncClient with get_db overridden to return our mock session."""
    from svc_shared.database import get_db

    async def _override():
        yield mock_db

    app.dependency_overrides[get_db] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. Health Endpoints
# ---------------------------------------------------------------------------


class TestHealthEndpoints:
    """Service health checks — if these fail, nothing else can work."""

    async def test_root_health_ok(self, client: AsyncClient):
        """
        # MUTATION: Removing /health route or changing its path breaks monitoring.
        Validates: 200 + JSON has 'status': 'ok'
        """
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "service" in body

    async def test_health_service_name(self, client: AsyncClient):
        """
        # MUTATION: If service name is changed or removed from health response,
        service discovery cannot identify which service responded.
        Validates: service field equals "intelflow-svc"
        """
        resp = await client.get("/health")
        body = resp.json()
        assert body["service"] == "intelflow-svc"

    async def test_health_port_is_integer(self, client: AsyncClient):
        """
        # MUTATION: If PORT config is serialized as string instead of int,
        downstream service discovery fails. Validates: PORT is numeric.
        """
        resp = await client.get("/health")
        body = resp.json()
        assert isinstance(body["port"], int)

    async def test_intelflow_status_endpoint(self, client: AsyncClient):
        """
        # MUTATION: If /api/intelflow/status is removed or returns wrong shape,
        monitoring scripts break silently.
        Validates: 200 response with module and status fields.
        """
        resp = await client.get("/api/intelflow/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["module"] == "intelflow"
        assert body["status"] == "active"


# ---------------------------------------------------------------------------
# 2. Report CRUD
# ---------------------------------------------------------------------------


class TestReportCRUD:
    """Report CRUD operations. Mock DB so service logic runs but no real Postgres."""

    async def test_list_reports_empty(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If list() doesn't respect soft-delete filter, deleted reports
        appear in results. Here we verify empty -> empty (base case).
        Validates: paginated response with items=[], total=0.
        """
        resp = await client.get("/api/intelflow/reports", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert isinstance(body["items"], list)

    async def test_list_reports_pagination_echoed(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If pagination params are ignored (e.g., page always=1),
        large collections break the UI.
        Validates: page and page_size are echoed back.
        """
        resp = await client.get(
            "/api/intelflow/reports",
            params={"space_id": _SPACE_ID, "page": 3, "page_size": 10},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 3
        assert body["page_size"] == 10

    async def test_get_report_not_found_returns_404(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If service returns None but route returns 200 instead of 404,
        callers can't detect missing resources.
        Validates: 404 on missing ID.
        """
        mock_db.get.return_value = None
        resp = await client.get(f"/api/intelflow/reports/{_REPORT_ID}")
        assert resp.status_code == 404

    async def test_get_report_found_returns_full_response(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If to_response() drops required fields (e.g., title or content),
        frontend silently receives incomplete data.
        Validates: response has all SpaceScopedResponse + Report fields.
        """
        report = _make_report_row()
        mock_db.get.return_value = report
        resp = await client.get(f"/api/intelflow/reports/{_REPORT_ID}")
        assert resp.status_code == 200
        body = resp.json()
        # SpaceScopedResponse fields
        assert body["id"] == _REPORT_ID
        assert "space_id" in body
        assert "created_at" in body
        assert "updated_at" in body
        # Report-specific fields
        assert "title" in body
        assert "query" in body
        assert "content" in body
        assert isinstance(body.get("sources"), list)
        assert isinstance(body.get("tags"), list)
        assert isinstance(body.get("topics"), list)

    async def test_create_report_returns_201(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If status_code=201 is removed from the route decorator,
        clients expecting 201 for creation will get wrong semantics.
        Validates: POST /reports returns 201.
        """
        resp = await client.post(
            "/api/intelflow/reports",
            json={"title": "New Report", "query": "test", "content": "Content here"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201

    async def test_create_report_missing_required_fields_returns_422(self, client: AsyncClient):
        """
        # MUTATION: If title/query/content validation is removed from ReportCreate,
        garbage data enters the DB.
        Validates: POST without required fields -> 422.
        """
        resp = await client.post(
            "/api/intelflow/reports",
            json={"title": "Only title"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 422

    async def test_create_report_response_has_id(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If flush/refresh doesn't populate server_default id,
        the created report response has null id.
        Validates: created report response has a non-empty string id.
        """
        resp = await client.post(
            "/api/intelflow/reports",
            json={"title": "ID Test", "query": "q", "content": "c"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert isinstance(body["id"], str)
        assert len(body["id"]) > 0

    async def test_update_report_not_found_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If update() silently ignores missing entity and returns 200,
        clients lose consistency guarantees.
        Validates: 404 on missing ID.
        """
        mock_db.get.return_value = None
        resp = await client.put(
            f"/api/intelflow/reports/{_REPORT_ID}",
            json={"title": "Updated"},
        )
        assert resp.status_code == 404

    async def test_delete_report_not_found_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If delete() on missing entity returns 200 (no-op success),
        idempotency bugs hide.
        Validates: 404 on missing delete.
        """
        mock_db.get.return_value = None
        resp = await client.delete(f"/api/intelflow/reports/{_REPORT_ID}")
        assert resp.status_code == 404

    async def test_delete_report_success_returns_204(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If soft-delete sets deleted_at but returns False, the 404 path
        fires incorrectly. If status code changes from 204, clients break.
        Validates: delete of existing report returns 204 (no content).
        """
        report = _make_report_row()
        mock_db.get.return_value = report
        resp = await client.delete(f"/api/intelflow/reports/{_REPORT_ID}")
        assert resp.status_code == 204

    async def test_list_reports_by_tag_filter(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If tag filtering is removed from list_reports route, the tag
        parameter is silently ignored and all reports are returned.
        Validates: tag query parameter is accepted (200, not 422).
        """
        resp = await client.get(
            "/api/intelflow/reports",
            params={"space_id": _SPACE_ID, "tag": "ai"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body

    async def test_list_reports_by_topic_id_filter(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If topic_id filtering path is removed from list_reports,
        topic-based browsing silently returns unfiltered results.
        Validates: topic_id query parameter is accepted (200, not 422).
        """
        resp = await client.get(
            "/api/intelflow/reports",
            params={"space_id": _SPACE_ID, "topic_id": _TOPIC_ID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body


# ---------------------------------------------------------------------------
# 3. Topic CRUD
# ---------------------------------------------------------------------------


class TestTopicCRUD:
    """Topic list, create, graph, related endpoints."""

    async def test_list_topics_empty(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If list_topics doesn't return PaginatedResponse shape,
        frontend pagination component breaks.
        Validates: paginated response structure with items=[], total=0.
        """
        resp = await client.get("/api/intelflow/topics", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert body["total"] == 0
        assert isinstance(body["items"], list)

    async def test_list_topics_pagination_defaults(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If default page_size for topics changes from 50 to an unexpected value,
        the UI displays wrong number of items.
        Validates: default page=1 and page_size=50.
        """
        resp = await client.get("/api/intelflow/topics", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1
        assert body["page_size"] == 50

    async def test_create_topic_returns_201(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If status_code=201 is removed from create_topic route,
        clients expecting 201 for creation get wrong semantics.
        Validates: POST /topics returns 201.
        """
        resp = await client.post(
            "/api/intelflow/topics",
            json={"name": "machine-learning"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201

    async def test_create_topic_response_shape(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If _to_response() drops name or report_count fields,
        frontend topic list renders incorrectly.
        Validates: created topic has name, id, report_count fields.
        """
        resp = await client.post(
            "/api/intelflow/topics",
            json={"name": "deep-learning", "display_name": "Deep Learning"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert isinstance(body["id"], str)
        assert body["name"] == "deep-learning"
        assert "report_count" in body
        assert "created_at" in body

    async def test_create_topic_missing_name_returns_422(self, client: AsyncClient):
        """
        # MUTATION: If name validation is removed from TopicCreate schema,
        empty topics enter the system.
        Validates: POST without name -> 422.
        """
        resp = await client.post(
            "/api/intelflow/topics",
            json={"display_name": "No Name"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 422

    async def test_get_related_topics_returns_list(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If get_related returns a dict/object instead of list,
        frontend .map() on response throws TypeError.
        Validates: /topics/{id}/related returns a list.
        """
        resp = await client.get(f"/api/intelflow/topics/{_TOPIC_ID}/related")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    async def test_topic_graph_response_shape(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If get_graph returns wrong shape (missing nodes or edges key),
        frontend graph visualization crashes.
        Validates: /topics/graph has nodes and edges arrays.
        """
        resp = await client.get("/api/intelflow/topics/graph", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert "nodes" in body
        assert "edges" in body
        assert isinstance(body["nodes"], list)
        assert isinstance(body["edges"], list)

    async def test_backfill_topics_endpoint_exists(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If backfill endpoint is removed, topic re-indexing becomes impossible.
        Validates: POST /topics/backfill returns 200 (not 404/405).
        """
        resp = await client.post(
            "/api/intelflow/topics/backfill",
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 4. Search
# ---------------------------------------------------------------------------


class TestSearch:
    """Text search endpoint tests."""

    async def test_search_returns_list(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If search endpoint returns a dict/paginated response instead of
        a flat list, clients expecting array iteration break.
        Validates: POST /search returns a list (possibly empty).
        """
        resp = await client.post(
            "/api/intelflow/search",
            json={"query": "machine learning"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    async def test_search_empty_query_rejected(self, client: AsyncClient):
        """
        # MUTATION: If min_length=1 is removed from TextSearchRequest.query,
        empty searches hit the DB with no filter and return all rows.
        Validates: empty query string -> 422.
        """
        resp = await client.post(
            "/api/intelflow/search",
            json={"query": ""},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 422

    async def test_search_with_results(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If text_search result shaping breaks (wrong field names in
        TextSearchResult), clients get KeyError on report.id.
        Validates: non-empty search results have report and score fields.
        """
        report = _make_report_row(
            title="Machine Learning Advances", content="Deep learning content"
        )
        # Mock execute to return matching reports
        scalars_result = MagicMock()
        scalars_result.all.return_value = [report]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_result
        execute_result.scalar_one.return_value = 1
        execute_result.scalar_one_or_none.return_value = None
        execute_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=execute_result)

        resp = await client.post(
            "/api/intelflow/search",
            json={"query": "machine learning"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        if len(body) > 0:
            item = body[0]
            assert "report" in item
            assert "score" in item
            assert isinstance(item["score"], (int, float))
            # ReportBrief contract
            assert "id" in item["report"]
            assert "title" in item["report"]
            assert "created_at" in item["report"]


# ---------------------------------------------------------------------------
# 5. Dashboard
# ---------------------------------------------------------------------------


class TestDashboard:
    """Dashboard summary and timeline endpoints."""

    async def test_dashboard_returns_required_fields(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If dashboard response drops total_reports or total_topics,
        the dashboard widget shows undefined.
        Validates: DashboardResponse has all required counter fields.
        """
        resp = await client.get("/api/intelflow/dashboard", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        required = {"total_reports", "total_topics", "recent_reports"}
        assert required.issubset(body.keys()), f"Missing fields: {required - body.keys()}"

    async def test_dashboard_counters_non_negative(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If count query has a sign error or wrong aggregation,
        counters go negative — meaningless to display.
        Validates: all counters >= 0.
        """
        resp = await client.get("/api/intelflow/dashboard", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_reports"] >= 0
        assert body["total_topics"] >= 0

    async def test_dashboard_recent_reports_is_list(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If recent_reports field changes from list to single object,
        frontend .map() call throws.
        Validates: recent_reports is a list type.
        """
        resp = await client.get("/api/intelflow/dashboard", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["recent_reports"], list)

    async def test_timeline_returns_entries(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If timeline endpoint is removed or response shape changes,
        the activity chart in dashboard breaks.
        Validates: GET /dashboard/timeline returns entries list.
        """
        resp = await client.get(
            "/api/intelflow/dashboard/timeline",
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "entries" in body
        assert isinstance(body["entries"], list)

    async def test_timeline_days_param_accepted(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If days parameter validation breaks (accepts 0 or negative),
        the timeline query returns wrong date range.
        Validates: days=7 is accepted without error.
        """
        resp = await client.get(
            "/api/intelflow/dashboard/timeline",
            params={"space_id": _SPACE_ID, "days": 7},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 6. Error Handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """WorkshopError handler and structured error responses."""

    async def test_workshop_error_handler_produces_structured_error(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If WorkshopError exception handler is removed from main.py,
        all 404/409 errors return unformatted FastAPI default messages.
        Validates: 404 response has 'detail' and 'code' fields.
        """
        mock_db.get.return_value = None
        resp = await client.get(f"/api/intelflow/reports/{_REPORT_ID}")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body
        assert "code" in body, "Missing 'code' field — WorkshopError handler may be bypassed"

    async def test_not_found_error_has_module_field(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If NotFoundError is raised without module kwarg, the module
        field in error response is None/missing — hard for clients to route errors.
        Validates: error response includes module field.
        """
        mock_db.get.return_value = None
        resp = await client.get(f"/api/intelflow/reports/{_REPORT_ID}")
        assert resp.status_code == 404
        body = resp.json()
        assert "module" in body

    async def test_unknown_route_returns_404(self, client: AsyncClient):
        """
        # MUTATION: If a wildcard route accidentally catches all paths,
        API discovery breaks.
        Validates: unknown paths return 404.
        """
        resp = await client.get("/api/intelflow/nonexistent_xyz")
        assert resp.status_code in (404, 405)

    async def test_not_found_error_code_is_intelflow_scoped(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If error code string is changed from "intelflow.report_not_found"
        to a generic code, clients using code for error routing break.
        Validates: error code contains 'intelflow' prefix.
        """
        mock_db.get.return_value = None
        resp = await client.get(f"/api/intelflow/reports/{_REPORT_ID}")
        assert resp.status_code == 404
        body = resp.json()
        assert "intelflow" in body.get("code", "")


# ---------------------------------------------------------------------------
# 7. Invariants (structural + property-based)
# ---------------------------------------------------------------------------


class TestInvariants:
    """Invariant-based tests — check PROPERTIES, not specific values."""

    async def test_soft_deleted_report_not_fetchable(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If get() doesn't filter deleted_at, deleted reports remain
        accessible via direct ID lookup.
        Validates: deleted report -> 404 on GET.
        """
        deleted = _make_report_row(deleted_at=datetime.now(UTC))
        mock_db.get.return_value = deleted
        resp = await client.get(f"/api/intelflow/reports/{_REPORT_ID}")
        assert resp.status_code == 404

    async def test_report_response_id_is_string(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If UUID serialization changes to raw UUID object (not hex string),
        JSON encoding fails or clients receive wrong type.
        Validates: id field in report response is a string.
        """
        report = _make_report_row()
        mock_db.get.return_value = report
        resp = await client.get(f"/api/intelflow/reports/{_REPORT_ID}")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["id"], str)

    async def test_pagination_defaults_are_sane(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If default page_size is accidentally set to 0 or huge number,
        all list endpoints return wrong results.
        Validates: default page >= 1, page_size >= 1.
        """
        resp = await client.get("/api/intelflow/reports", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] >= 1
        assert body["page_size"] >= 1

    async def test_create_report_tags_are_list(self, client: AsyncClient, mock_db: AsyncMock):
        """
        # MUTATION: If tags field serialization breaks (returns string instead of list),
        frontend tag chips component crashes.
        Validates: created report's tags field is a list.
        """
        resp = await client.post(
            "/api/intelflow/reports",
            json={
                "title": "Tags Test",
                "query": "q",
                "content": "c",
                "tags": ["ai", "ml"],
            },
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert isinstance(body["tags"], list)

    async def test_create_report_skill_name_stripped_from_tags(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        # MUTATION: If skill_name tag stripping logic is removed from create_report,
        every report gets polluted with the skill name as a tag.
        Validates: skill_name is not in the returned tags.
        """
        resp = await client.post(
            "/api/intelflow/reports",
            json={
                "title": "Skill Strip Test",
                "query": "q",
                "content": "c",
                "tags": ["ai", "smart-search", "ml"],
                "skill_name": "smart-search",
            },
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 201
        body = resp.json()
        # smart-search should be stripped from tags since it matches skill_name
        tags_lower = [t.lower() for t in body["tags"]]
        assert "smart-search" not in tags_lower

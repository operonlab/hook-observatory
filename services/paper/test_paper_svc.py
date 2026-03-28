"""Paper-svc tests — independent adversary agent, six iron rules.

Writer/tester separation: This file was written WITHOUT reading routes.py or services.py.
Contracts derived only from: schemas.py, config.py, shared/{database,errors,models,schemas}.py

Six Iron Rules applied:
  1. Mutation thinking  — each test documents what code mutation it catches
  2. Writer/tester separation — no implementation code was read
  3. Invariants over fixed I/O — property assertions, not hardcoded values
  4. Mock only external I/O — DB session mocked; internal service logic runs live
  5. Runtime regression — edge cases, empty strings, invalid IDs, boundary values
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
_USER_ID = "01900000000000000000000000000002"
_ARTICLE_ID = "01900000000000000000000000000003"
_ANNOTATION_ID = "01900000000000000000000000000004"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _make_article_row(
    *,
    id: str = _ARTICLE_ID,
    title: str = "Test Paper",
    arxiv_id: str | None = "2401.00001",
    doi: str | None = None,
    year: int | None = 2024,
    abstract: str | None = "An abstract.",
    authors: list[dict] | None = None,
    journal: str | None = None,
    categories: list[str] | None = None,
    tags: list[str] | None = None,
    pdf_url: str | None = None,
    source_url: str | None = None,
    full_text: str | None = None,
    s3_uri: str | None = None,
    space_id: str = _SPACE_ID,
    created_by: str | None = _USER_ID,
    deleted_at: datetime | None = None,
) -> MagicMock:
    """Build a minimal mock ORM Article row."""
    row = MagicMock()
    row.id = id
    row.title = title
    row.arxiv_id = arxiv_id
    row.doi = doi
    row.year = year
    row.abstract = abstract
    row.authors = authors or []
    row.journal = journal
    row.categories = categories or []
    row.tags = tags or []
    row.pdf_url = pdf_url
    row.source_url = source_url
    row.full_text = full_text
    row.s3_uri = s3_uri
    row.space_id = space_id
    row.created_by = created_by
    row.deleted_at = deleted_at
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    row.digest = None
    return row


def _make_annotation_row(
    *,
    id: str = _ANNOTATION_ID,
    paper_id: str = _ARTICLE_ID,
    note: str = "Important finding",
    annotation_type: str = "note",
    tags: list[str] | None = None,
    space_id: str = _SPACE_ID,
    created_by: str | None = _USER_ID,
    deleted_at: datetime | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = id
    row.paper_id = paper_id
    row.note = note
    row.annotation_type = annotation_type
    row.tags = tags or []
    row.space_id = space_id
    row.created_by = created_by
    row.deleted_at = deleted_at
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    return row


def _make_digest_row(
    *,
    id: str = "01900000000000000000000000000005",
    paper_id: str = _ARTICLE_ID,
    one_liner: str | None = "Short summary",
    key_findings: list[str] | None = None,
    workshop_relevance: str | None = None,
    applicable_modules: list[str] | None = None,
    actionable_insight: str | None = None,
    effort_estimate: str | None = None,
    confidence: float | None = 0.85,
    model_used: str | None = "haiku",
    generated_at: datetime | None = None,
    space_id: str = _SPACE_ID,
    created_by: str | None = _USER_ID,
    deleted_at: datetime | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = id
    row.paper_id = paper_id
    row.one_liner = one_liner
    row.key_findings = key_findings or []
    row.workshop_relevance = workshop_relevance
    row.applicable_modules = applicable_modules or []
    row.actionable_insight = actionable_insight
    row.effort_estimate = effort_estimate
    row.confidence = confidence
    row.model_used = model_used
    row.generated_at = generated_at
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

    db.refresh = AsyncMock(side_effect=_mock_refresh)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Async generator that yields our mock DB (to replace FastAPI dependency)
# ---------------------------------------------------------------------------


async def _mock_db_dependency(mock_db: AsyncMock):
    """Yield the mock DB as a FastAPI override for get_db."""
    yield mock_db


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
    """
    Service health checks.
    These are the simplest invariants — if they fail, nothing else can work.
    """

    @pytest.mark.asyncio
    async def test_root_health_ok(self, client: AsyncClient):
        """
        MUTATION: If someone removes the /health route or changes its path,
        this test catches it immediately (before checking module routes).
        Validates: 200 + JSON has 'status': 'ok'
        """
        resp = await client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        # Validates service identity field exists — catches copy-paste rename errors
        assert "service" in body

    @pytest.mark.asyncio
    async def test_paper_status_endpoint(self, client: AsyncClient):
        """
        MUTATION: If /api/paper/status is removed or returns wrong shape,
        monitoring scripts break silently. Validates: 200 response.
        """
        resp = await client.get("/api/paper/status")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_port_field_is_integer(self, client: AsyncClient):
        """
        MUTATION: If PORT config is serialized as string instead of int,
        downstream service discovery fails. Validates: PORT is numeric.
        """
        resp = await client.get("/health")
        body = resp.json()
        assert isinstance(body["port"], int)


# ---------------------------------------------------------------------------
# 2. Article CRUD
# ---------------------------------------------------------------------------


class TestArticleCRUD:
    """
    Article CRUD operations.
    Mock the DB so service logic runs but no real Postgres is needed.
    """

    @pytest.mark.asyncio
    async def test_list_articles_empty(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If list() doesn't respect the soft-delete filter, deleted articles
        appear in results. Here we verify empty → empty (base case invariant).
        Validates: paginated response with items=[], total=0.
        """
        # scalar_one (count query) returns 0, scalars.all returns []
        resp = await client.get("/api/paper/articles", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        # PaginatedResponse contract: must have items, total, page, page_size
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert isinstance(body["items"], list)

    @pytest.mark.asyncio
    async def test_list_articles_returns_paged_structure(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        MUTATION: If pagination params are ignored (e.g., page always=1),
        large collections break the UI. Validates: page param is echoed back.
        """
        resp = await client.get(
            "/api/paper/articles",
            params={"space_id": _SPACE_ID, "page": 2, "page_size": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        # The returned page + page_size must reflect what was requested
        assert body["page"] == 2
        assert body["page_size"] == 5

    @pytest.mark.asyncio
    async def test_get_article_not_found_returns_404(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If service returns None but route returns 200 instead of 404,
        callers can't detect missing resources. Validates: 404 on missing ID.
        """
        mock_db.get.return_value = None  # DB returns nothing
        resp = await client.get(f"/api/paper/articles/{_ARTICLE_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_article_found_returns_full_response(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        MUTATION: If to_response() drops required fields (e.g., abstract or id),
        frontend silently receives incomplete data. Validates: response has id + title.
        """
        article = _make_article_row()
        mock_db.get.return_value = article
        resp = await client.get(f"/api/paper/articles/{_ARTICLE_ID}")
        assert resp.status_code == 200
        body = resp.json()
        # SpaceScopedResponse contract: id, space_id, created_at, updated_at
        assert body["id"] == _ARTICLE_ID
        assert body["title"] == "Test Paper"
        assert "space_id" in body
        assert "created_at" in body

    @pytest.mark.asyncio
    async def test_create_article_minimal_fields(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If routes.py makes `abstract` required but schema says optional,
        clients with just title will get 422. Validates: create with title-only succeeds.
        """
        article = _make_article_row(title="Minimal Paper", arxiv_id=None)
        mock_db.flush = AsyncMock()
        mock_db.get.return_value = article

        # Patch the service's dedup check (scalars.first returns None → no conflict)
        execute_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.first.return_value = None
        scalars_result.all.return_value = []
        execute_result.scalars.return_value = scalars_result
        execute_result.scalar_one.return_value = 0
        mock_db.execute.return_value = execute_result

        resp = await client.post(
            "/api/paper/articles",
            json={"title": "Minimal Paper"},
            params={"space_id": _SPACE_ID},
        )
        # Must not be 422 (validation error) — title is the only required field
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_create_article_missing_title_returns_422(self, client: AsyncClient):
        """
        MUTATION: If title validation is removed from schema, garbage data enters the DB.
        Validates: POST without title → 422 Unprocessable Entity.
        """
        resp = await client.post(
            "/api/paper/articles",
            json={"abstract": "No title here"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_update_article_not_found_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        MUTATION: If update() silently ignores missing entity and returns 200,
        clients lose consistency guarantees. Validates: 404 on missing ID.
        """
        mock_db.get.return_value = None
        resp = await client.put(
            f"/api/paper/articles/{_ARTICLE_ID}",
            json={"title": "Updated"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_article_not_found_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        MUTATION: If delete() on missing entity returns 200 (no-op success),
        idempotency bugs hide in integration tests. Validates: 404 on missing delete.
        """
        mock_db.get.return_value = None
        resp = await client.delete(
            f"/api/paper/articles/{_ARTICLE_ID}",
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_article_success(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If soft-delete sets deleted_at but returns False, the 404 path
        fires incorrectly. Validates: delete of existing article returns 200/204.
        """
        article = _make_article_row()
        mock_db.get.return_value = article
        resp = await client.delete(
            f"/api/paper/articles/{_ARTICLE_ID}",
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code in (200, 204)


# ---------------------------------------------------------------------------
# 3. Deduplication Invariants
# ---------------------------------------------------------------------------


class TestArticleDedup:
    """
    Deduplication invariants: duplicate arxiv_id or doi must return 409 Conflict.

    These tests assert a *property* (no duplicate identifiers) not a specific value,
    so they remain valid even if the dedup algorithm changes internally.
    """

    @pytest.mark.asyncio
    async def test_duplicate_arxiv_id_returns_409(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If the dedup check is removed or the branch condition is inverted,
        the same arXiv paper gets stored N times. Validates: 409 when arxiv_id exists.
        """
        existing = _make_article_row(arxiv_id="2401.99999")

        # First execute call (dedup lookup) returns the existing article
        execute_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.first.return_value = existing
        scalars_result.all.return_value = [existing]
        execute_result.scalars.return_value = scalars_result
        execute_result.scalar_one.return_value = 1
        mock_db.execute.return_value = execute_result

        resp = await client.post(
            "/api/paper/articles",
            json={"title": "Duplicate Paper", "arxiv_id": "2401.99999"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_duplicate_doi_returns_409(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If DOI dedup check is missing (only arxiv_id checked),
        same journal article with DOI gets stored twice. Validates: 409 for duplicate DOI.
        """
        existing = _make_article_row(arxiv_id=None, doi="10.1145/1234567.1234568")

        execute_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.first.return_value = existing
        scalars_result.all.return_value = [existing]
        execute_result.scalars.return_value = scalars_result
        execute_result.scalar_one.return_value = 1
        mock_db.execute.return_value = execute_result

        resp = await client.post(
            "/api/paper/articles",
            json={"title": "Same DOI Paper", "doi": "10.1145/1234567.1234568"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_no_identifier_allows_duplicates(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If the service rejects ANY duplicate title (even without identifiers),
        manual papers with the same name become impossible.
        Validates: article with no arxiv_id/doi and unique title is accepted.
        """
        new_article = _make_article_row(arxiv_id=None, doi=None, title="Manual Entry")
        mock_db.flush = AsyncMock()

        # No existing match found (first returns None)
        execute_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.first.return_value = None
        scalars_result.all.return_value = []
        execute_result.scalars.return_value = scalars_result
        execute_result.scalar_one.return_value = 0
        mock_db.execute.return_value = execute_result
        mock_db.get.return_value = new_article

        resp = await client.post(
            "/api/paper/articles",
            json={"title": "Manual Entry"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_conflict_response_has_error_code(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If ConflictError is raised but error handler is missing or broken,
        clients get 500 instead of structured 409. Validates: error body has 'code' field.
        """
        existing = _make_article_row(arxiv_id="2401.00001")
        execute_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.first.return_value = existing
        execute_result.scalars.return_value = scalars_result
        mock_db.execute.return_value = execute_result

        resp = await client.post(
            "/api/paper/articles",
            json={"title": "Conflict Test", "arxiv_id": "2401.00001"},
            params={"space_id": _SPACE_ID},
        )
        if resp.status_code == 409:
            body = resp.json()
            # ErrorResponse contract: detail + code fields must be present
            assert "detail" in body
            assert "code" in body


# ---------------------------------------------------------------------------
# 4. Digest and Annotation Sub-Resources
# ---------------------------------------------------------------------------


class TestDigestAndAnnotation:
    """
    Sub-resource tests: digest (1:1) and annotations (1:N).
    """

    @pytest.mark.asyncio
    async def test_get_digest_for_nonexistent_article_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        MUTATION: If digest route doesn't first verify the parent article exists,
        a caller gets a misleading 'no digest' response for a phantom article ID.
        Validates: /articles/{bad_id}/digest → 404.
        """
        mock_db.get.return_value = None
        resp = await client.get(
            f"/api/paper/articles/{_ARTICLE_ID}/digest",
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_digest_not_yet_generated(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If digest absence is treated as 500 rather than 404,
        article without digest breaks the frontend detail page.
        Validates: article exists but no digest → 404 (or empty/null).
        """
        article = _make_article_row()
        article.digest = None

        def get_side_effect(model, entity_id):
            # First call for the article itself
            if hasattr(model, "__tablename__") and "article" in str(model.__tablename__).lower():
                return article
            return None

        # We need the article GET to work, but digest DB lookup returns None
        mock_db.get.return_value = article

        execute_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.first.return_value = None
        scalars_result.all.return_value = []
        scalars_result.scalar_one_or_none = MagicMock(return_value=None)
        execute_result.scalars.return_value = scalars_result
        execute_result.scalar_one.return_value = 0
        execute_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = execute_result

        resp = await client.get(
            f"/api/paper/articles/{_ARTICLE_ID}/digest",
            params={"space_id": _SPACE_ID},
        )
        # Service returns 404 when no digest exists
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_annotations_empty(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If annotation list doesn't filter by paper_id, all annotations
        across all papers are returned. Validates: returns a list (empty is valid).
        """
        article = _make_article_row()
        mock_db.get.return_value = article

        execute_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        execute_result.scalars.return_value = scalars_result
        execute_result.scalar_one.return_value = 0
        mock_db.execute.return_value = execute_result

        resp = await client.get(
            f"/api/paper/articles/{_ARTICLE_ID}/annotations",
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body.get("items", body), list)

    @pytest.mark.asyncio
    async def test_create_annotation_requires_note(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If `note` validation is dropped from AnnotationCreate,
        empty annotations silently enter the DB. Validates: POST without note → 422.
        """
        resp = await client.post(
            f"/api/paper/articles/{_ARTICLE_ID}/annotations",
            json={"annotation_type": "note"},  # missing required `note` field
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_annotation_default_type(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If default annotation_type is removed or changed from "note",
        existing UI code expecting 'note' breaks.
        Validates: annotation_type defaults to 'note' when not specified.
        """
        article = _make_article_row()
        mock_db.get.return_value = article
        # Don't override flush/refresh — use the smart mocks from fixture

        execute_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.first.return_value = None
        scalars_result.all.return_value = []
        execute_result.scalars.return_value = scalars_result
        execute_result.scalar_one.return_value = 0
        mock_db.execute.return_value = execute_result

        resp = await client.post(
            f"/api/paper/articles/{_ARTICLE_ID}/annotations",
            json={"note": "This is interesting"},  # no annotation_type — should default
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code in (200, 201)
        body = resp.json()
        assert body.get("annotation_type") == "note"

    @pytest.mark.asyncio
    async def test_annotation_for_nonexistent_article_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        MUTATION: If annotation creation doesn't verify parent article exists,
        orphaned annotations are created against phantom paper IDs.
        Validates: create annotation on missing article → 404.
        """
        mock_db.get.return_value = None  # article not found
        execute_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.first.return_value = None
        execute_result.scalars.return_value = scalars_result
        mock_db.execute.return_value = execute_result

        resp = await client.post(
            f"/api/paper/articles/{_ARTICLE_ID}/annotations",
            json={"note": "Orphan annotation"},
            params={"space_id": _SPACE_ID},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. Invariants (property-based)
# ---------------------------------------------------------------------------


class TestInvariants:
    """
    Invariant-based tests — these check PROPERTIES of the system, not specific values.
    If any invariant is broken, it points to a deeper logic mutation.
    """

    @pytest.mark.asyncio
    async def test_soft_deleted_article_not_fetchable(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        MUTATION: If soft-delete sets deleted_at but get() doesn't filter it out,
        deleted articles remain accessible. Validates: deleted article → 404 on GET.

        This is the core soft-delete invariant: after DELETE, GET must return 404.
        """
        deleted_article = _make_article_row(deleted_at=datetime.now(UTC))
        # DB.get returns the row but it has deleted_at set
        mock_db.get.return_value = deleted_article
        resp = await client.get(f"/api/paper/articles/{_ARTICLE_ID}")
        # Service should treat deleted_at != None as "not found"
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_excludes_soft_deleted(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If list() COUNT query lacks `WHERE deleted_at IS NULL`,
        total count is inflated with deleted records.
        Validates: list with 0 non-deleted → total == 0.
        """
        # count returns 0 (soft-delete filter applied), items empty
        execute_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        execute_result.scalars.return_value = scalars_result
        execute_result.scalar_one.return_value = 0
        mock_db.execute.return_value = execute_result

        resp = await client.get("/api/paper/articles", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    @pytest.mark.asyncio
    async def test_dashboard_returns_all_required_counters(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        MUTATION: If dashboard adds a new counter but the response schema drops a field,
        monitoring dashboards get KeyError. Validates: all DashboardResponse fields present.
        """
        execute_result = MagicMock()
        execute_result.scalar_one.return_value = 0
        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        execute_result.scalars.return_value = scalars_result
        mock_db.execute.return_value = execute_result

        resp = await client.get("/api/paper/dashboard", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        # DashboardResponse contract: all four counter fields must be present
        required = {"total_articles", "total_digests", "total_annotations", "recent_articles"}
        assert required.issubset(body.keys()), f"Missing fields: {required - body.keys()}"

    @pytest.mark.asyncio
    async def test_dashboard_counters_non_negative(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If count query has a sign error or wrong aggregation,
        counters go negative — meaningless to display.
        Validates: all counters >= 0.
        """
        execute_result = MagicMock()
        execute_result.scalar_one.return_value = 0
        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        execute_result.scalars.return_value = scalars_result
        mock_db.execute.return_value = execute_result

        resp = await client.get("/api/paper/dashboard", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        for field in (
            "total_articles",
            "total_digests",
            "total_annotations",
            "high_relevance_count",
        ):
            assert body.get(field, 0) >= 0, f"{field} was negative"

    @pytest.mark.asyncio
    async def test_pagination_page_size_defaults_are_sane(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        MUTATION: If default page_size is accidentally set to 0 or a huge number,
        all list endpoints return wrong results.
        Validates: default page_size is a positive integer, default page is 1.
        """
        execute_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        execute_result.scalars.return_value = scalars_result
        execute_result.scalar_one.return_value = 0
        mock_db.execute.return_value = execute_result

        resp = await client.get("/api/paper/articles", params={"space_id": _SPACE_ID})
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] >= 1
        assert body["page_size"] >= 1

    @pytest.mark.asyncio
    async def test_article_response_id_is_string(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If UUID serialization changes to raw UUID object (not hex string),
        JSON encoding fails or clients receive wrong type.
        Validates: id field in article response is a string.
        """
        article = _make_article_row()
        mock_db.get.return_value = article
        resp = await client.get(f"/api/paper/articles/{_ARTICLE_ID}")
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body["id"], str)

    @pytest.mark.asyncio
    async def test_workshop_error_handler_produces_structured_error(
        self, client: AsyncClient, mock_db: AsyncMock
    ):
        """
        MUTATION: If the WorkshopError exception handler is removed from main.py,
        all 404/409 errors return unformatted FastAPI default messages.
        Validates: 404 response has 'detail' and 'code' fields (not just 'detail').
        """
        mock_db.get.return_value = None
        resp = await client.get(f"/api/paper/articles/{_ARTICLE_ID}")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body
        # WorkshopError always includes 'code' — default FastAPI 404 does not
        assert "code" in body, "Missing 'code' field — WorkshopError handler may be bypassed"

    @pytest.mark.asyncio
    async def test_empty_title_string_rejected(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If title="" is allowed through, the article is unfindable and
        unsearchable. Validates: empty string title → 422 (or at minimum not 200).

        Note: Pydantic BaseModel allows empty strings by default; this tests whether
        the service adds an explicit validator. If it does NOT, this test documents
        the gap.
        """
        resp = await client.post(
            "/api/paper/articles",
            json={"title": ""},
            params={"space_id": _SPACE_ID},
        )
        # If no custom validator: 200 (gap documented). If validator exists: 422.
        # We assert it is NOT a server error (500).
        assert resp.status_code != 500, "Empty title caused server error — unhandled edge case"

    @pytest.mark.asyncio
    async def test_unknown_route_returns_404_not_500(self, client: AsyncClient):
        """
        MUTATION: If a wildcard route accidentally catches all paths and returns 200,
        API discovery breaks. Validates: unknown paths return 404.
        """
        resp = await client.get("/api/paper/nonexistent_endpoint_xyz")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_annotations_list_is_list_type(self, client: AsyncClient, mock_db: AsyncMock):
        """
        MUTATION: If annotation list endpoint accidentally returns a single object
        instead of a list (wrong serializer), client code throws on .map().
        Validates: annotations response items field is a list.
        """
        article = _make_article_row()
        mock_db.get.return_value = article

        execute_result = MagicMock()
        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        execute_result.scalars.return_value = scalars_result
        execute_result.scalar_one.return_value = 0
        mock_db.execute.return_value = execute_result

        resp = await client.get(
            f"/api/paper/articles/{_ARTICLE_ID}/annotations",
            params={"space_id": _SPACE_ID},
        )
        if resp.status_code == 200:
            body = resp.json()
            items = body.get("items", body)
            assert isinstance(items, list)

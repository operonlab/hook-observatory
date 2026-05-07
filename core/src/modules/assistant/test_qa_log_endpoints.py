"""Minimal pytest for QA log endpoints — GET /qa-logs + POST /qa-logs/{id}/flag."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Minimal app fixture ──────────────────────────────────────────────────────


def _make_app(user_role: str = "admin") -> FastAPI:
    """Build an isolated FastAPI app with the assistant router mounted."""
    app = FastAPI()

    # Patch require_permission to return a fixed user dict
    def _fake_require(permission: str):
        from fastapi import Depends

        def _dep():
            if user_role == "forbidden":
                from src.shared.errors import ForbiddenError
                raise ForbiddenError("no permission", code="admin.forbidden")
            return {"id": "test-user", "role": user_role, "space_id": "default"}

        return Depends(_dep)

    with patch("src.shared.deps.require_permission", side_effect=_fake_require):
        from .routes import router

    app.include_router(router, prefix="/assistant")
    return app


def _fake_qa_log(flagged: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id="abc123",
        session_id="sess001",
        question="what is memvault?",
        answer="it stores memories",
        tokens_in=10,
        tokens_out=20,
        duration_ms=500,
        flagged=flagged,
        flag_reason=None,
        created_at=datetime(2026, 5, 6, 12, 0, 0),
    )


# ── 200 GET /qa-logs ─────────────────────────────────────────────────────────


def test_list_qa_logs_200():
    """GET /qa-logs returns 200 with list payload for admin user."""
    app = FastAPI()

    from src.shared import deps as _deps_mod

    def _fake_require(permission: str):
        from fastapi import Depends

        def _dep():
            return {"id": "test-user", "role": "admin", "space_id": "default"}

        return Depends(_dep)

    with (
        patch.object(_deps_mod, "require_permission", side_effect=_fake_require),
        patch("src.modules.assistant.services.list_qa_logs", new_callable=AsyncMock) as mock_list,
        patch("src.shared.database.get_db"),
    ):
        mock_list.return_value = [_fake_qa_log()]

        # Provide a fake async db session via Depends override
        async def _fake_db():
            yield MagicMock()

        from .routes import router

        app.include_router(router, prefix="/assistant")

        # Override get_db
        from src.shared import deps as deps_mod

        app.dependency_overrides[deps_mod.get_db] = _fake_db

        client = TestClient(app)
        resp = client.get("/assistant/qa-logs?limit=10")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["id"] == "abc123"
    assert data[0]["flagged"] is False


# ── 200 POST /qa-logs/{id}/flag ──────────────────────────────────────────────


def test_flag_qa_log_200():
    """POST /qa-logs/{id}/flag returns 200 with updated record for admin user."""
    app = FastAPI()

    from src.shared import deps as _deps_mod

    def _fake_require(permission: str):
        from fastapi import Depends

        def _dep():
            return {"id": "test-user", "role": "admin", "space_id": "default"}

        return Depends(_dep)

    flagged_record = _fake_qa_log(flagged=True)
    flagged_record.flag_reason = "wrong answer"

    with (
        patch.object(_deps_mod, "require_permission", side_effect=_fake_require),
        patch("src.modules.assistant.services.flag_qa_log", new_callable=AsyncMock) as mock_flag,
    ):
        mock_flag.return_value = flagged_record

        async def _fake_db():
            yield MagicMock()

        from .routes import router

        app.include_router(router, prefix="/assistant")

        from src.shared import deps as deps_mod

        app.dependency_overrides[deps_mod.get_db] = _fake_db

        client = TestClient(app)
        resp = client.post("/assistant/qa-logs/abc123/flag", json={"reason": "wrong answer"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["flagged"] is True
    assert data["flag_reason"] == "wrong answer"


# ── 403 沒權限 ───────────────────────────────────────────────────────────────


def test_get_qa_logs_403_no_permission():
    """GET /qa-logs returns 403 when user lacks admin.read permission."""
    app = FastAPI()

    from src.shared import deps as _deps_mod
    from src.shared.errors import ForbiddenError

    def _fake_require(permission: str):
        from fastapi import Depends

        def _dep():
            raise ForbiddenError("no permission", code="admin.forbidden")

        return Depends(_dep)

    with patch.object(_deps_mod, "require_permission", side_effect=_fake_require):
        from .routes import router

        app.include_router(router, prefix="/assistant")

    # Register exception handler to match production behaviour
    from fastapi.responses import JSONResponse

    @app.exception_handler(ForbiddenError)
    async def _forbidden_handler(request, exc):
        return JSONResponse(status_code=403, content={"detail": exc.detail})

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/assistant/qa-logs")
    assert resp.status_code == 403

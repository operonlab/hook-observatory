"""Capture pipeline routes."""

import asyncio
import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import ForbiddenError, NotFoundError
from src.shared.schemas import PaginatedResponse

from .registry import get_permissions
from .schemas import (
    BATCH_LIMIT,
    BatchFillRequest,
    CaptureCreate,
    CaptureEnrichmentResponse,
    CapturePromoteResult,
    CaptureResponse,
    CaptureSearchResult,
    CaptureStats,
    CaptureUpdate,
)
from .services import capture_service

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_user_prefs(db: AsyncSession, user_id: str) -> dict:
    """Fetch user preferences for smart defaults."""
    from src.modules.auth.services import user_service

    try:
        return await user_service.get_preferences(db, user_id)
    except Exception:
        return {}


def _check_owner(capture, user: dict) -> None:
    """Ensure the current user owns this capture (or is admin)."""
    if user.get("role") == "admin":
        return
    if capture.created_by != user.get("id"):
        raise ForbiddenError("Not the owner of this capture", code="capture.forbidden")


@router.post("", response_model=CaptureResponse, status_code=201)
async def create_capture(
    data: CaptureCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.write"),
):
    user_prefs = await _get_user_prefs(db, user["id"])
    capture = await capture_service.create(
        db, space_id, data, user_id=user.get("id"), user_prefs=user_prefs
    )
    await db.commit()
    return capture_service.to_response(capture)


@router.get("", response_model=PaginatedResponse[CaptureResponse])
async def list_captures(
    space_id: str = Query("default"),
    module: str | None = None,
    entity_type: str | None = None,
    status: str = "pending",
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0, le=10000),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.read"),
):
    items, total = await capture_service.list(
        db,
        space_id,
        module=module,
        entity_type=entity_type,
        status=status,
        limit=limit,
        offset=offset,
        user_id=user.get("id"),
    )
    page = (offset // limit) + 1 if limit > 0 else 1
    return PaginatedResponse(
        items=[capture_service.to_response(c) for c in items],
        total=total,
        page=page,
        page_size=limit,
    )


@router.get("/stats", response_model=CaptureStats)
async def capture_stats(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.read"),
):
    return await capture_service.stats(db, space_id, user_id=user.get("id"))


@router.get("/events/stream")
async def capture_events_stream(
    request: Request,
    _user: dict = require_permission("capture.read"),
):
    """SSE stream — emits 'changed' events when captures are created/enriched/promoted."""
    from sse_starlette.sse import EventSourceResponse

    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _capture_sse_clients.add(queue)

    async def generate():
        try:
            yield {"event": "connected", "data": "ok"}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield msg
                except TimeoutError:
                    yield {"event": "keepalive", "data": ""}
        finally:
            _capture_sse_clients.discard(queue)

    return EventSourceResponse(generate())


@router.get("/search", response_model=list[CaptureSearchResult])
async def search_captures(
    q: str = Query(..., description="Search query string"),
    space_id: str = Query("default"),
    module: str | None = None,
    entity_type: str | None = None,
    status: str | None = None,
    top_k: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.read"),
):
    """Search captures using Qdrant hybrid search with ILIKE fallback."""
    results = await capture_service.search(
        db,
        q,
        space_id,
        module=module,
        entity_type=entity_type,
        status=status,
        top_k=top_k,
        user_id=user.get("id"),
    )
    return [
        CaptureSearchResult(capture=capture_service.to_response(c), score=score)
        for c, score in results
    ]


@router.post("/batch/promote", response_model=list[CapturePromoteResult])
async def batch_promote(
    capture_ids: list[str] = Query(max_length=BATCH_LIMIT),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.write"),
):
    results = await capture_service.batch_promote(db, capture_ids, user_id=user.get("id"))
    await db.commit()
    return results


@router.patch("/batch/fill", response_model=list[CaptureResponse])
async def batch_fill(
    data: BatchFillRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.write"),
):
    user_prefs = await _get_user_prefs(db, user["id"])
    responses = []
    try:
        for cid in data.capture_ids:
            capture = await capture_service.get(db, cid)
            if not capture:
                raise NotFoundError("capture", cid)
            _check_owner(capture, user)
            capture = await capture_service.update(
                db, cid, CaptureUpdate(payload=data.payload), user_prefs=user_prefs
            )
            responses.append(capture_service.to_response(capture))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return responses


@router.get("/fill-options")
async def fill_options(
    module: str,
    entity_type: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.read"),
):
    """Return selectable options for reference fields (wallet_id, category_id, etc.)."""
    return await capture_service.resolve_fill_options(
        db, module, entity_type, space_id, user_id=user.get("id")
    )


@router.get("/{capture_id}", response_model=CaptureResponse)
async def get_capture(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.read"),
):
    capture = await capture_service.get(db, capture_id)
    if not capture:
        raise NotFoundError("capture", capture_id)
    _check_owner(capture, user)
    return capture_service.to_response(capture)


@router.patch("/{capture_id}", response_model=CaptureResponse)
async def update_capture(
    capture_id: str,
    data: CaptureUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.write"),
):
    capture = await capture_service.get(db, capture_id)
    if not capture:
        raise NotFoundError("capture", capture_id)
    _check_owner(capture, user)
    user_prefs = await _get_user_prefs(db, user["id"])
    capture = await capture_service.update(db, capture_id, data, user_prefs=user_prefs)
    await db.commit()
    return capture_service.to_response(capture)


@router.post("/{capture_id}/promote", response_model=CapturePromoteResult)
async def promote_capture(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.write"),
):
    capture = await capture_service.get(db, capture_id)
    if not capture:
        raise NotFoundError("capture", capture_id)
    _check_owner(capture, user)
    # Verify user has write permission on target module (manifest-driven)
    target_perm = get_permissions().get(capture.module)
    if target_perm:
        from src.modules.auth.permissions import has_permission

        if not has_permission(user.get("role", "guest"), target_perm):
            raise ForbiddenError(
                f"Permission denied: {target_perm}", code=f"{capture.module}.forbidden"
            )
    result = await capture_service.promote(db, capture_id, user_id=user.get("id"))
    if result.success:
        await db.commit()
    else:
        await db.rollback()
    return result


@router.post("/{capture_id}/enrich", response_model=CaptureResponse)
async def enrich_capture(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.write"),
):
    """Run LLM enrichment pipeline on a pending capture."""
    capture = await capture_service.get(db, capture_id)
    if not capture:
        raise NotFoundError("capture", capture_id)
    _check_owner(capture, user)
    result = await capture_service.enrich(db, capture_id, user_id=user.get("id"))
    await db.commit()
    return capture_service.to_response(result)


@router.delete("/{capture_id}", status_code=204)
async def delete_capture(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.write"),
):
    capture = await capture_service.get(db, capture_id)
    if not capture:
        raise NotFoundError("capture", capture_id)
    _check_owner(capture, user)
    await capture_service.delete(db, capture_id)
    await db.commit()


@router.post("/expire-stale")
async def expire_stale_captures(
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("admin.write"),
):
    count = await capture_service.expire_stale(db)
    await db.commit()
    return {"expired": count}


@router.get("/{capture_id}/enrichments", response_model=list[CaptureEnrichmentResponse])
async def get_enrichments(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.read"),
):
    capture = await capture_service.get(db, capture_id)
    if not capture:
        raise NotFoundError("capture", capture_id)
    _check_owner(capture, user)
    enrichments = await capture_service.get_enrichments(db, capture_id)
    return enrichments


# ─── SSE: push notifications on capture changes ───

_capture_sse_clients: set[asyncio.Queue] = set()


def _notify_capture_changed(event_type: str) -> None:
    """Queue a 'changed' notification to all SSE clients."""
    dead: set[asyncio.Queue] = set()
    for q in _capture_sse_clients:
        try:
            q.put_nowait({"event": "changed", "data": event_type})
        except asyncio.QueueFull:
            dead.add(q)
    _capture_sse_clients.difference_update(dead)


def register_capture_sse_events() -> None:
    """Subscribe to capture EventBus events for SSE broadcast."""
    from src.events.bus import event_bus

    for evt in ("capture.created", "capture.enriched", "capture.promoted"):
        event_bus.subscribe(evt, lambda e: _notify_capture_changed(e.type))

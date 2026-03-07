"""Capture pipeline routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import ForbiddenError

from .schemas import (
    BatchFillRequest,
    CaptureCreate,
    CaptureEnrichmentResponse,
    CapturePromoteResult,
    CaptureResponse,
    CaptureStats,
    CaptureUpdate,
)
from .services import capture_service

router = APIRouter()


async def _get_user_prefs(db: AsyncSession, user_id: str) -> dict:
    """Fetch user preferences for smart defaults."""
    from src.modules.auth.services import user_service

    return await user_service.get_preferences(db, user_id)


def _check_owner(capture, user: dict) -> None:
    """Ensure the current user owns this capture."""
    if capture.created_by and capture.created_by != user.get("id"):
        raise ForbiddenError("Not the owner of this capture", code="capture.forbidden")


# Permission mapping: promote checks target module's write permission
_MODULE_WRITE_PERMS = {
    "finance": "finance.write",
    "invest": "invest.write",
    "taskflow": "taskflow.write",
    "ideagraph": "ideagraph.write",
    "intelflow": "intelflow.write",
}


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


@router.get("", response_model=list[CaptureResponse])
async def list_captures(
    space_id: str = Query("default"),
    module: str | None = None,
    entity_type: str | None = None,
    status: str = "pending",
    limit: int = Query(50, le=100),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.read"),
):
    items, _total = await capture_service.list(
        db, space_id, module=module, entity_type=entity_type, status=status,
        limit=limit, offset=offset, user_id=user.get("id"),
    )
    return [capture_service.to_response(c) for c in items]


@router.get("/stats", response_model=CaptureStats)
async def capture_stats(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.read"),
):
    return await capture_service.stats(db, space_id, user_id=user.get("id"))


@router.post("/batch/promote", response_model=list[CapturePromoteResult])
async def batch_promote(
    capture_ids: list[str],
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.write"),
):
    results = await capture_service.batch_promote(
        db, capture_ids, user_id=user.get("id")
    )
    await db.commit()
    return results


@router.patch("/batch/fill", response_model=list[CaptureResponse])
async def batch_fill(
    data: BatchFillRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.write"),
):
    from .schemas import CaptureUpdate

    responses = []
    for cid in data.capture_ids:
        capture = await capture_service.get(db, cid)
        if not capture:
            from src.shared.errors import NotFoundError

            raise NotFoundError("capture", cid)
        _check_owner(capture, user)
        user_prefs = await _get_user_prefs(db, user["id"])
        capture = await capture_service.update(
            db, cid, CaptureUpdate(payload=data.payload), user_prefs=user_prefs
        )
        responses.append(capture_service.to_response(capture))
    await db.commit()
    return responses


@router.get("/{capture_id}", response_model=CaptureResponse)
async def get_capture(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.read"),
):
    capture = await capture_service.get(db, capture_id)
    if not capture:
        from src.shared.errors import NotFoundError

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
        from src.shared.errors import NotFoundError

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
        from src.shared.errors import NotFoundError

        raise NotFoundError("capture", capture_id)
    _check_owner(capture, user)
    # Verify user has write permission on target module
    target_perm = _MODULE_WRITE_PERMS.get(capture.module)
    if target_perm:
        from src.modules.auth.permissions import has_permission

        if not has_permission(user.get("role", "guest"), target_perm):
            raise ForbiddenError(
                f"Permission denied: {target_perm}", code=f"{capture.module}.forbidden"
            )
    result = await capture_service.promote(db, capture_id, user_id=user.get("id"))
    await db.commit()
    return result


@router.delete("/{capture_id}", status_code=204)
async def delete_capture(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.write"),
):
    capture = await capture_service.get(db, capture_id)
    if not capture:
        from src.shared.errors import NotFoundError

        raise NotFoundError("capture", capture_id)
    _check_owner(capture, user)
    await capture_service.delete(db, capture_id)
    await db.commit()


@router.get("/{capture_id}/enrichments", response_model=list[CaptureEnrichmentResponse])
async def get_enrichments(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.read"),
):
    capture = await capture_service.get(db, capture_id)
    if not capture:
        from src.shared.errors import NotFoundError

        raise NotFoundError("capture", capture_id)
    _check_owner(capture, user)
    enrichments = await capture_service.get_enrichments(db, capture_id)
    return enrichments

"""Capture pipeline routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_current_user, get_db

from .schemas import (
    CaptureCreate,
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


@router.post("", response_model=CaptureResponse, status_code=201)
async def create_capture(
    data: CaptureCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
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
    user: dict = Depends(get_current_user),
):
    items, _total = await capture_service.list(
        db, space_id, module=module, entity_type=entity_type, status=status,
        limit=limit, offset=offset,
    )
    return [capture_service.to_response(c) for c in items]


@router.get("/stats", response_model=CaptureStats)
async def capture_stats(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    return await capture_service.stats(db, space_id)


@router.get("/{capture_id}", response_model=CaptureResponse)
async def get_capture(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    capture = await capture_service.get(db, capture_id)
    if not capture:
        from src.shared.errors import NotFoundError
        raise NotFoundError("capture", capture_id)
    return capture_service.to_response(capture)


@router.patch("/{capture_id}", response_model=CaptureResponse)
async def update_capture(
    capture_id: str,
    data: CaptureUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    user_prefs = await _get_user_prefs(db, user["id"])
    capture = await capture_service.update(db, capture_id, data, user_prefs=user_prefs)
    await db.commit()
    return capture_service.to_response(capture)


@router.post("/{capture_id}/promote", response_model=CapturePromoteResult)
async def promote_capture(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    result = await capture_service.promote(db, capture_id, user_id=user.get("id"))
    await db.commit()
    return result


@router.delete("/{capture_id}", status_code=204)
async def delete_capture(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await capture_service.delete(db, capture_id)
    await db.commit()

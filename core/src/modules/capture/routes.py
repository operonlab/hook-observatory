"""Capture pipeline routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import ForbiddenError

from .registry import get_permissions
from .schemas import (
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

router = APIRouter()


async def _get_user_prefs(db: AsyncSession, user_id: str) -> dict:
    """Fetch user preferences for smart defaults."""
    from src.modules.auth.services import user_service

    try:
        return await user_service.get_preferences(db, user_id)
    except Exception:
        return {}


def _check_owner(capture, user: dict) -> None:
    """Ensure the current user owns this capture."""
    if capture.created_by and capture.created_by != user.get("id"):
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
        db,
        space_id,
        module=module,
        entity_type=entity_type,
        status=status,
        limit=limit,
        offset=offset,
        user_id=user.get("id"),
    )
    return [capture_service.to_response(c) for c in items]


@router.get("/stats", response_model=CaptureStats)
async def capture_stats(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.read"),
):
    return await capture_service.stats(db, space_id, user_id=user.get("id"))


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
    import logging

    from sqlalchemy import select

    from src.shared.qdrant_client import is_available as qdrant_available
    from src.shared.qdrant_search import hybrid_search as qdrant_hybrid_search
    from src.shared.search_types import SearchConfig

    from .models import Capture

    logger = logging.getLogger(__name__)
    user_id = user.get("id")

    # --- Qdrant path ---
    if qdrant_available():
        config = SearchConfig(
            top_k=top_k,
            service_ids=["capture"],
        )
        results, _meta = await qdrant_hybrid_search(q, space_id, config)

        if results:
            # Fetch full Capture records by entity_id
            entity_ids = [r.entity_id for r in results]
            score_map = {r.entity_id: r.score for r in results}

            stmt = select(Capture).where(
                Capture.id.in_(entity_ids),
                Capture.space_id == space_id,
                Capture.deleted_at.is_(None),
            )
            if user_id:
                stmt = stmt.where(Capture.created_by == user_id)
            if module:
                stmt = stmt.where(Capture.module == module)
            if entity_type:
                stmt = stmt.where(Capture.entity_type == entity_type)
            if status is not None:
                stmt = stmt.where(Capture.status == status)

            rows = (await db.execute(stmt)).scalars().all()
            # Preserve Qdrant score order
            id_to_capture = {c.id: c for c in rows}
            return [
                CaptureSearchResult(
                    capture=capture_service.to_response(id_to_capture[eid]),
                    score=score_map[eid],
                )
                for eid in entity_ids
                if eid in id_to_capture
            ]

        logger.debug(
            "Qdrant returned 0 results for capture space=%s query=%r — falling back to ILIKE",
            space_id, q,
        )

    # --- ILIKE fallback ---
    pattern = f"%{q}%"
    stmt = select(Capture).where(
        Capture.space_id == space_id,
        Capture.raw_input.ilike(pattern),
        Capture.deleted_at.is_(None),
    )
    if user_id:
        stmt = stmt.where(Capture.created_by == user_id)
    if module:
        stmt = stmt.where(Capture.module == module)
    if entity_type:
        stmt = stmt.where(Capture.entity_type == entity_type)
    if status is not None:
        stmt = stmt.where(Capture.status == status)

    stmt = stmt.order_by(Capture.updated_at.desc()).limit(top_k)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        CaptureSearchResult(capture=capture_service.to_response(c), score=1.0)
        for c in rows
    ]


@router.post("/batch/promote", response_model=list[CapturePromoteResult])
async def batch_promote(
    capture_ids: list[str],
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


@router.get("/fill-options")
async def fill_options(
    module: str,
    entity_type: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("capture.read"),
):
    """Return selectable options for reference fields (wallet_id, category_id, etc.)."""
    from .registry import get_adapter

    adapter = get_adapter(module, entity_type)
    if not adapter or not getattr(adapter, "reference_fields", None):
        return {}

    options: dict[str, list[dict[str, str]]] = {}
    for field, resolver_key in adapter.reference_fields.items():
        parts = resolver_key.split(".")
        if parts[0] == "finance" and parts[1] == "wallet":
            from src.modules.finance.services import wallet_service

            result = await wallet_service.list(db, space_id, user_id=user.get("id"))
            options[field] = [{"id": w.id, "name": w.name} for w in result.items]
        elif parts[0] == "finance" and parts[1] == "category":
            from src.modules.finance.services import category_service

            result = await category_service.list(db, space_id, user_id=user.get("id"))
            options[field] = [{"id": c.id, "name": c.name} for c in result.items]
        elif parts[0] == "invest" and parts[1] == "account":
            from src.modules.invest.services import account_service

            result = await account_service.list(db, space_id)
            options[field] = [{"id": a.id, "name": a.name} for a in result.items]
    return options


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
        from src.shared.errors import NotFoundError

        raise NotFoundError("capture", capture_id)
    _check_owner(capture, user)
    enrichments = await capture_service.get_enrichments(db, capture_id)
    return enrichments

"""Admin routes — audit trail API.

Prefix: /api/admin (mounted in main.py)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.schemas import PaginatedResponse, PaginationParams

from .schemas import AuditLogResponse
from .services import audit_service

router = APIRouter(tags=["admin"])


@router.get("/status")
async def admin_status():
    return {"module": "admin", "status": "active"}


@router.get("/audit", response_model=PaginatedResponse[AuditLogResponse])
async def list_audit_logs(
    module: str | None = Query(None),
    entity_type: str | None = Query(None),
    user_id: str | None = Query(None),
    space_id: str | None = Query(None),
    action: str | None = Query(None, description="created/updated/deleted/restored/purged"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("admin.read"),
):
    return await audit_service.list_logs(
        db,
        pagination=PaginationParams(page=page, page_size=page_size),
        module=module,
        entity_type=entity_type,
        user_id=user_id,
        space_id=space_id,
        action=action,
    )


@router.get(
    "/audit/{module}/{entity_type}/{entity_id}",
    response_model=list[AuditLogResponse],
)
async def get_entity_history(
    module: str,
    entity_type: str,
    entity_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("admin.read"),
):
    return await audit_service.get_entity_history(db, module, entity_type, entity_id)

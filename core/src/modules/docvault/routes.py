"""DocVault REST API routes.

Endpoints for document CRUD, QA, relations, coverage gaps, and stats.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.schemas import PaginatedResponse

from .deps import (
    coverage_service,
    document_service,
    qa_log_service,
    relation_service,
    version_service,
)
from .schemas import (
    CoverageGapResponse,
    CoverageGapUpdate,
    DocumentCreate,
    DocumentRelationCreate,
    DocumentRelationResponse,
    DocumentResponse,
    DocumentUpdate,
    DocumentVersionResponse,
    DocvaultStats,
    GapStats,
    QALogResponse,
    QARequest,
    QAResponse,
)

router = APIRouter(prefix="/docvault", tags=["docvault"])


# ======================== Documents ========================


@router.get(
    "/documents",
    response_model=PaginatedResponse[DocumentResponse],
)
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    source_type: str | None = None,
    tag: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.read"),
):
    return await document_service.list(
        db,
        space_id=user["space_id"],
        page=page,
        page_size=page_size,
        filters={
            "status": status,
            "source_type": source_type,
            "tag": tag,
        },
    )


@router.post(
    "/documents",
    response_model=DocumentResponse,
    status_code=201,
)
async def create_document(
    data: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.write"),
):
    return await document_service.create(db, data, space_id=user["space_id"], created_by=user["id"])


@router.get("/documents/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.read"),
):
    return await document_service.get(db, doc_id, space_id=user["space_id"])


@router.patch(
    "/documents/{doc_id}",
    response_model=DocumentResponse,
)
async def update_document(
    doc_id: str,
    data: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.write"),
):
    return await document_service.update(db, doc_id, data, space_id=user["space_id"])


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.write"),
):
    await document_service.delete(db, doc_id, space_id=user["space_id"])


# ======================== Versions ========================


@router.get(
    "/documents/{doc_id}/versions",
    response_model=list[DocumentVersionResponse],
)
async def list_versions(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.read"),
):
    return await version_service.list_by_document(db, doc_id, space_id=user["space_id"])


@router.post(
    "/documents/{doc_id}/supersede",
    response_model=DocumentVersionResponse,
)
async def supersede_document(
    doc_id: str,
    raw_content: str,
    content_hash: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.write"),
):
    return await document_service.supersede(
        db,
        doc_id,
        raw_content=raw_content,
        content_hash=content_hash,
        space_id=user["space_id"],
        created_by=user["id"],
    )


# ======================== QA ========================


@router.post("/qa", response_model=QAResponse)
async def qa(
    req: QARequest,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.read"),
):
    # TODO: wire to qa_service pipeline orchestration
    _ = db, user, req
    return QAResponse(answer="Not implemented yet", pipeline_used="A")


@router.post("/qa/{qa_log_id}/feedback")
async def qa_feedback(
    qa_log_id: str,
    feedback: str = Query(..., pattern="^(positive|negative)$"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.write"),
):
    return await qa_log_service.set_feedback(db, qa_log_id, feedback, space_id=user["space_id"])


# ======================== Relations ========================


@router.get(
    "/documents/{doc_id}/relations",
    response_model=list[DocumentRelationResponse],
)
async def list_relations(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.read"),
):
    return await relation_service.list_by_document(db, doc_id, space_id=user["space_id"])


@router.post(
    "/relations",
    response_model=DocumentRelationResponse,
    status_code=201,
)
async def create_relation(
    data: DocumentRelationCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.write"),
):
    return await relation_service.create(db, data, space_id=user["space_id"], created_by=user["id"])


# ======================== Coverage Gaps ========================


@router.get(
    "/gaps",
    response_model=PaginatedResponse[CoverageGapResponse],
)
async def list_gaps(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.read"),
):
    return await coverage_service.list(
        db,
        space_id=user["space_id"],
        page=page,
        page_size=page_size,
        status=status,
    )


@router.patch("/gaps/{gap_id}", response_model=CoverageGapResponse)
async def update_gap(
    gap_id: str,
    data: CoverageGapUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.write"),
):
    return await coverage_service.update(db, gap_id, data, space_id=user["space_id"])


@router.get("/gaps/stats", response_model=GapStats)
async def gap_stats(
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.read"),
):
    return await coverage_service.stats(db, space_id=user["space_id"])


# ======================== QA Logs ========================


@router.get(
    "/qa-logs",
    response_model=PaginatedResponse[QALogResponse],
)
async def list_qa_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.read"),
):
    return await qa_log_service.list(
        db,
        space_id=user["space_id"],
        page=page,
        page_size=page_size,
    )


# ======================== Stats ========================


@router.get("/stats", response_model=DocvaultStats)
async def stats(
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.read"),
):
    return await document_service.stats(db, space_id=user["space_id"])


# ======================== Admin ========================


@router.post("/documents/{doc_id}/reindex", status_code=202)
async def reindex_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("docvault.write"),
):
    await document_service.reindex(db, doc_id, space_id=user["space_id"])
    return {"status": "reindex_queued", "document_id": doc_id}

"""DocVault routes — REST API endpoints.

Prefix: /api/docvault (mounted in main.py)

Endpoints:
  GET/POST      /documents                          — list/create
  GET/PUT/DELETE /documents/{id}                    — detail/update/delete
  GET            /documents/{id}/versions            — list versions
  GET            /documents/{id}/chunks              — list chunks
  GET            /documents/{id}/relations           — list relations
  POST           /documents/{id}/relations           — create relation
  POST           /search                             — semantic search (stub)
  POST           /qa                                 — QA pipeline (stub)
  GET/POST       /qa/logs                            — list/create QA logs
  GET            /qa/logs/{id}                       — get QA log
  PATCH          /qa/logs/{id}/feedback              — record feedback
  GET            /gaps                               — list coverage gaps
  POST           /gaps                               — create gap
  PATCH          /gaps/{id}                          — update gap
  GET            /dashboard                          — stats
  GET            /status                             — health check
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import ConflictError, NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from .schemas import (
    CoverageGapCreate,
    CoverageGapResponse,
    CoverageGapUpdate,
    DocumentChunkResponse,
    DocumentCreate,
    DocumentRelationCreate,
    DocumentRelationResponse,
    DocumentResponse,
    DocumentUpdate,
    DocumentVersionResponse,
    DocvaultDashboardResponse,
    QAFeedbackUpdate,
    QALogCreate,
    QALogResponse,
    QARequest,
    QAResponse,
)
from .services import (
    chunk_service,
    coverage_gap_service,
    dashboard_service,
    document_service,
    qa_log_service,
    relation_service,
    version_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["docvault"])


# ======================== Documents ========================


@router.get("/documents", response_model=PaginatedResponse[DocumentResponse])
async def list_documents(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tag: str | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated tags"),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    tag_list = None
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    elif tag:
        tag_list = [tag]

    if tag_list:
        return await document_service.list_by_tags(db, space_id, tag_list, pagination)
    return await document_service.list(db, space_id, pagination)


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    instance = await document_service.get_in_space(db, document_id, space_id)
    if not instance:
        raise NotFoundError("Document not found", code="docvault.document_not_found")
    return document_service.to_response(instance)


@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def create_document(
    body: DocumentCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.write"),
):
    # Dedup by content_hash
    existing = await document_service.get_by_content_hash(db, body.content_hash)
    if existing:
        raise ConflictError(
            f"Document with content_hash={body.content_hash} already exists",
            code="docvault.content_hash_conflict",
        )

    instance = await document_service.create(db, space_id, body)
    await db.commit()
    await db.refresh(instance)
    return document_service.to_response(instance)


@router.put("/documents/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: str,
    body: DocumentUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.write"),
):
    instance = await document_service.update(db, document_id, body, space_id=space_id)
    if not instance:
        raise NotFoundError("Document not found", code="docvault.document_not_found")
    await db.commit()
    await db.refresh(instance)
    return document_service.to_response(instance)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.write"),
):
    deleted = await document_service.delete(db, document_id, space_id=space_id)
    if not deleted:
        raise NotFoundError("Document not found", code="docvault.document_not_found")
    await db.commit()


# ======================== Versions ========================


@router.get(
    "/documents/{document_id}/versions",
    response_model=PaginatedResponse[DocumentVersionResponse],
)
async def list_versions(
    document_id: str,
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    doc = await document_service.get_in_space(db, document_id, space_id)
    if not doc:
        raise NotFoundError("Document not found", code="docvault.document_not_found")
    pagination = PaginationParams(page=page, page_size=page_size)
    return await version_service.list_by_document(db, document_id, pagination)


# ======================== Chunks ========================


@router.get(
    "/documents/{document_id}/chunks",
    response_model=PaginatedResponse[DocumentChunkResponse],
)
async def list_chunks(
    document_id: str,
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    doc = await document_service.get_in_space(db, document_id, space_id)
    if not doc:
        raise NotFoundError("Document not found", code="docvault.document_not_found")
    pagination = PaginationParams(page=page, page_size=page_size)
    return await chunk_service.list_by_document(db, document_id, pagination)


# ======================== Relations ========================


@router.get(
    "/documents/{document_id}/relations",
    response_model=PaginatedResponse[DocumentRelationResponse],
)
async def list_relations(
    document_id: str,
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    doc = await document_service.get_in_space(db, document_id, space_id)
    if not doc:
        raise NotFoundError("Document not found", code="docvault.document_not_found")
    pagination = PaginationParams(page=page, page_size=page_size)
    return await relation_service.list_by_document(db, document_id, pagination)


@router.post(
    "/documents/{document_id}/relations",
    response_model=DocumentRelationResponse,
    status_code=201,
)
async def create_relation(
    document_id: str,
    body: DocumentRelationCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.write"),
):
    doc = await document_service.get_in_space(db, document_id, space_id)
    if not doc:
        raise NotFoundError("Document not found", code="docvault.document_not_found")
    instance = await relation_service.create(db, space_id, body)
    await db.commit()
    await db.refresh(instance)
    return relation_service.to_response(instance)


# ======================== Search (stub) ========================


@router.post("/search")
async def search_documents(
    q: str = Query(..., min_length=1, max_length=2000),
    top_k: int = Query(10, ge=1, le=100),
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    """Semantic search over document chunks. Stub — Phase 1 ops will implement."""
    return {
        "results": [],
        "message": "Search not yet implemented. Phase 1 ops pending.",
    }


# ======================== QA Pipeline (stub) ========================


@router.post("/qa", response_model=QAResponse)
async def qa_question(
    body: QARequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    """Question-answering pipeline. Stub — Phase 1 ops will implement."""
    return QAResponse(
        question=body.question,
        answer="QA pipeline not yet implemented. Phase 1 ops pending.",
        citations=[],
        confidence=0.0,
        crag_verdict=None,
        pipeline_used="A",
    )


# ======================== QA Logs ========================


@router.get("/qa/logs", response_model=PaginatedResponse[QALogResponse])
async def list_qa_logs(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await qa_log_service.list(db, space_id, pagination)


@router.post("/qa/logs", response_model=QALogResponse, status_code=201)
async def create_qa_log(
    body: QALogCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.write"),
):
    instance = await qa_log_service.create(db, space_id, body)
    await db.commit()
    await db.refresh(instance)
    return qa_log_service.to_response(instance)


@router.get("/qa/logs/{qa_log_id}", response_model=QALogResponse)
async def get_qa_log(
    qa_log_id: str,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    instance = await qa_log_service.get_in_space(db, qa_log_id, space_id)
    if not instance:
        raise NotFoundError("QA log not found", code="docvault.qa_log_not_found")
    return qa_log_service.to_response(instance)


@router.patch("/qa/logs/{qa_log_id}/feedback", response_model=QALogResponse)
async def record_qa_feedback(
    qa_log_id: str,
    body: QAFeedbackUpdate,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.write"),
):
    instance = await qa_log_service.record_feedback(db, qa_log_id, body.feedback)
    if not instance:
        raise NotFoundError("QA log not found", code="docvault.qa_log_not_found")
    await db.commit()
    await db.refresh(instance)
    return qa_log_service.to_response(instance)


# ======================== Coverage Gaps ========================


@router.get("/gaps", response_model=PaginatedResponse[CoverageGapResponse])
async def list_gaps(
    space_id: str = Query("default"),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    if status:
        return await coverage_gap_service.list_by_status(db, space_id, status, pagination)
    return await coverage_gap_service.list(db, space_id, pagination)


@router.post("/gaps", response_model=CoverageGapResponse, status_code=201)
async def create_gap(
    body: CoverageGapCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.write"),
):
    instance = await coverage_gap_service.create(db, space_id, body)
    await db.commit()
    await db.refresh(instance)
    return coverage_gap_service.to_response(instance)


@router.patch("/gaps/{gap_id}", response_model=CoverageGapResponse)
async def update_gap(
    gap_id: str,
    body: CoverageGapUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.write"),
):
    instance = await coverage_gap_service.update(db, gap_id, body, space_id=space_id)
    if not instance:
        raise NotFoundError("Coverage gap not found", code="docvault.gap_not_found")
    await db.commit()
    await db.refresh(instance)
    return coverage_gap_service.to_response(instance)


# ======================== Dashboard ========================


@router.get("/dashboard", response_model=DocvaultDashboardResponse)
async def get_dashboard(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    return await dashboard_service.get_summary(db, space_id)


# ======================== Status ========================


@router.get("/status")
async def docvault_status():
    return {"module": "docvault", "status": "active", "phase": "1"}

"""DocVault routes — REST API endpoints.

Prefix: /api/docvault (mounted in main.py)

Endpoints:
  GET/POST      /documents                          — list/create
  POST           /documents/upload                   — upload file (full pipeline)
  GET/PUT/DELETE /documents/{id}                    — detail/update/delete
  GET            /documents/{id}/versions            — list versions
  GET            /documents/{id}/chunks              — list chunks
  GET            /documents/{id}/relations           — list relations
  POST           /documents/{id}/relations           — create relation
  POST           /search                             — semantic search
  POST           /qa                                 — QA pipeline
  GET/POST       /qa/logs                            — list/create QA logs
  GET            /qa/logs/{id}                       — get QA log
  PATCH          /qa/logs/{id}/feedback              — record feedback
  GET            /gaps                               — list coverage gaps
  POST           /gaps                               — create gap
  PATCH          /gaps/{id}                          — update gap
  GET            /dashboard                          — stats
  GET            /status                             — health check
"""

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import BadRequestError, ConflictError, NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from .ingest.parser import parse_document
from .ops.contextual_chunk import contextual_chunk
from .ops.flat_index import FlatIndexOp
from .schemas import (
    CoverageGapCreate,
    CoverageGapResponse,
    CoverageGapUpdate,
    DocumentChunkCreate,
    DocumentChunkResponse,
    DocumentCreate,
    DocumentRelationCreate,
    DocumentRelationResponse,
    DocumentResponse,
    DocumentSearchParams,
    DocumentSearchResponse,
    DocumentUpdate,
    DocumentUploadRequest,
    DocumentVersionCreate,
    DocumentVersionResponse,
    DocvaultDashboardResponse,
    QAFeedbackUpdate,
    QALogCreate,
    QALogResponse,
    QARequest,
    QAResponse,
    SearchChunkResult,
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

DOCVAULT_SERVICE_ID = "docvault-chunk"


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


@router.post("/documents/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    body: DocumentUploadRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.write"),
):
    """Upload a local file — full ingest pipeline: parse → Document → Version → Chunks → Qdrant."""
    file_path = body.file_path
    path = Path(file_path)
    if not path.exists():
        raise BadRequestError(f"File not found: {file_path}", code="docvault.file_not_found")

    # 1. Parse file
    raw_content, file_metadata = parse_document(file_path, body.source_type)
    if not raw_content.strip():
        raise BadRequestError("File is empty or unreadable", code="docvault.empty_file")

    # 2. Compute content hash + dedup
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    existing = await document_service.get_by_content_hash(db, content_hash)
    if existing:
        raise ConflictError(
            f"Document with content_hash={content_hash} already exists",
            code="docvault.content_hash_conflict",
        )

    # 3. Determine metadata
    title = body.title or file_metadata.get("title", path.stem)
    source_type = body.source_type or file_metadata.get("source_type", "markdown")

    # 4. Create Document record
    doc_create = DocumentCreate(
        title=title,
        source_type=source_type,
        source_uri=body.source_uri or str(path),
        content_hash=content_hash,
        tags=body.tags,
        metadata=body.metadata or file_metadata,
    )
    doc_instance = await document_service.create(db, space_id, doc_create)
    await db.flush()

    # 5. Create Version record
    ver_create = DocumentVersionCreate(
        document_id=doc_instance.id,
        version_number=1,
        content_hash=content_hash,
        raw_content=raw_content,
        extraction_model="pdfplumber" if source_type == "pdf" else "direct",
    )
    ver_instance = await version_service.create(db, space_id, ver_create)
    await db.flush()

    # 6. Chunk content
    chunks = contextual_chunk(raw_content, doc_title=title, extract_headings=True)

    # 7. Create Chunk records in DB + collect DB IDs for Qdrant indexing
    chunk_db_ids: list[str] = []
    for i, chunk_data in enumerate(chunks):
        chunk_create = DocumentChunkCreate(
            version_id=ver_instance.id,
            document_id=doc_instance.id,
            chunk_index=i,
            content=chunk_data["content"],
            section_path=chunk_data.get("section_path"),
            heading=chunk_data.get("heading"),
            page_range=chunk_data.get("page_range"),
            token_count=chunk_data.get("token_count", 0),
        )
        chunk_instance = await chunk_service.create(db, space_id, chunk_create)
        await db.flush()
        chunk_db_ids.append(chunk_instance.id)

    # 8. Update version chunk_count + status
    from .schemas import DocumentVersionUpdate

    await version_service.update(
        db,
        ver_instance.id,
        DocumentVersionUpdate(chunk_count=len(chunks), status="ready"),
        space_id=space_id,
    )

    # 9. Update document status + current_version_id
    doc_instance.current_version_id = ver_instance.id
    doc_instance.status = "indexed"

    await db.commit()
    await db.refresh(doc_instance)

    # 10. Index chunks in Qdrant (best-effort, don't fail upload if Qdrant is down)
    # Attach DB chunk IDs so FlatIndexOp uses them as entity_id (for DB lookups)
    for i, chunk_data in enumerate(chunks):
        if i < len(chunk_db_ids):
            chunk_data["db_id"] = chunk_db_ids[i]

    try:
        flat_index = FlatIndexOp()
        ctx = {
            "chunks": chunks,
            "document_id": doc_instance.id,
            "version_id": ver_instance.id,
            "space_id": space_id,
        }
        await flat_index(ctx)
        logger.info(
            "Indexed %d chunks for document %s", ctx.get("indexed_count", 0), doc_instance.id
        )
    except Exception:
        logger.exception("Qdrant indexing failed for document %s", doc_instance.id)

    return document_service.to_response(doc_instance)


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


# ======================== Search ========================


@router.post("/search", response_model=DocumentSearchResponse)
async def search_documents(
    body: DocumentSearchParams,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    """Semantic search over document chunks via Qdrant hybrid search."""
    from sqlalchemy import select

    from src.shared.qdrant_search import hybrid_search
    from src.shared.search_types import SearchConfig

    from .models import DocumentChunk

    config = SearchConfig(
        top_k=body.top_k,
        service_ids=[DOCVAULT_SERVICE_ID],
        tag_filter=body.tags,
    )
    results, _meta = await hybrid_search(body.q, space_id, config)

    # Fetch full chunk content from DB (Qdrant only stores 200-char preview)
    chunk_ids = [r.entity_id for r in results]
    full_content_map: dict[str, str] = {}
    if chunk_ids:
        rows = (
            await db.execute(
                select(DocumentChunk.id, DocumentChunk.content).where(
                    DocumentChunk.id.in_(chunk_ids)
                )
            )
        ).all()
        full_content_map = {row.id: row.content for row in rows}

    chunks = []
    for r in results:
        doc_id = r.metadata.get("document_id", r.entity_id)
        content = full_content_map.get(r.entity_id, r.content_preview)
        chunks.append(
            SearchChunkResult(
                document_id=doc_id,
                score=r.score,
                content=content,
                section_path=r.metadata.get("section_path", ""),
                page_range=r.metadata.get("page_range", ""),
                heading=r.metadata.get("heading", ""),
                chunk_index=r.metadata.get("chunk_index"),
            )
        )

    return DocumentSearchResponse(query=body.q, results=chunks, total=len(chunks))


# ======================== QA Pipeline ========================


@router.post("/qa", response_model=QAResponse)
async def qa_question(
    body: QARequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("docvault.read"),
):
    """QA pipeline: IntentRouter → Search/FanOut → DB enrich → Rerank → Synth → Log."""
    import hashlib as _hashlib

    from sqlalchemy import select

    from .models import DocumentChunk
    from .ops.cited_answer import CitedAnswerOp
    from .ops.fan_out import FanOutOp
    from .ops.hybrid_rrf_search import HybridRRFSearchOp
    from .ops.intent_router import IntentRouterOp
    from .ops.jina_rerank import JinaRerankOp
    from .ops.merge import MergeOp
    from .ops.query_expand import QueryExpandOp
    from .schemas import CitationRef

    # ── 1. Intent routing ──
    ctx: dict = {"query": body.question, "space_id": space_id, "top_k": body.top_k}
    await IntentRouterOp()(ctx)
    layer_plan = ctx.get("layer_plan", {})
    pipeline = layer_plan.get("pipeline", "A")

    # ── 2. Query expansion (multi-angle sub-queries for broader recall) ──
    try:
        await QueryExpandOp()(ctx)
    except Exception:
        logger.debug("QueryExpandOp failed, using original query only")

    # ── 3. Over-retrieve for reranking (use layer_plan top_k, not request top_k) ──
    ctx["top_k"] = layer_plan.get("docvault_top_k", body.top_k)
    if pipeline == "B":
        await FanOutOp()(ctx)
        await MergeOp()(ctx)
    else:
        await HybridRRFSearchOp()(ctx)

    # ── 3a. Neighbor expansion ──
    # For scattered-wisdom queries, the answer spans multiple non-adjacent sections.
    # Expand the evidence pool by pulling ±3 chunk_index neighbors of each hit,
    # then let the reranker filter down to the most relevant ones.
    evidence = ctx.get("evidence_chunks", [])
    hit_chunk_ids = {c.get("id", "") for c in evidence if c.get("id")}

    if hit_chunk_ids:
        # Get chunk_index and document_id for each hit
        hit_meta = (
            await db.execute(
                select(
                    DocumentChunk.document_id,
                    DocumentChunk.chunk_index,
                ).where(DocumentChunk.id.in_(hit_chunk_ids))
            )
        ).all()

        # Build target index ranges per document
        neighbor_ranges: dict[str, set[int]] = {}
        for doc_id, idx in hit_meta:
            if doc_id not in neighbor_ranges:
                neighbor_ranges[doc_id] = set()
            for offset in range(-3, 4):  # ±3
                neighbor_ranges[doc_id].add(idx + offset)

        # Fetch neighbor chunks not already in evidence

        for doc_id, indices in neighbor_ranges.items():
            neighbors = (
                await db.execute(
                    select(
                        DocumentChunk.id,
                        DocumentChunk.content,
                        DocumentChunk.section_path,
                        DocumentChunk.page_range,
                        DocumentChunk.heading,
                        DocumentChunk.chunk_index,
                    ).where(
                        DocumentChunk.document_id == doc_id,
                        DocumentChunk.chunk_index.in_(indices),
                        DocumentChunk.deleted_at == None,  # noqa: E711
                    )
                )
            ).all()

            for n in neighbors:
                if n.id not in hit_chunk_ids:
                    evidence.append(
                        {
                            "id": n.id,
                            "content": n.content,
                            "score": 0.1,  # low base score — reranker decides
                            "document_id": doc_id,
                            "section_path": n.section_path or "",
                            "page_range": n.page_range or "",
                            "heading": n.heading or "",
                            "chunk_index": n.chunk_index,
                        }
                    )
                    hit_chunk_ids.add(n.id)

        ctx["evidence_chunks"] = evidence
        logger.info(
            "Neighbor expansion: %d → %d chunks",
            len(hit_meta),
            len(evidence),
        )

    # ── 3b. Parent-child enrichment ──
    # Search found child chunks (small, precise). For LLM synthesis,
    # fetch the full parent section (all chunks sharing the same heading).
    evidence = ctx.get("evidence_chunks", [])
    chunk_ids = [c.get("id", "") for c in evidence if c.get("id")]
    if chunk_ids:
        # Step A: get child chunk metadata (document_id, heading)
        child_rows = (
            await db.execute(
                select(
                    DocumentChunk.id,
                    DocumentChunk.document_id,
                    DocumentChunk.heading,
                    DocumentChunk.content,
                ).where(DocumentChunk.id.in_(chunk_ids))
            )
        ).all()

        # Step B: for each unique (document_id, heading), fetch ALL sibling chunks
        seen_sections: set[tuple[str, str]] = set()
        parent_content_map: dict[str, str] = {}  # child_id → parent section content

        for row in child_rows:
            section_key = (row.document_id, row.heading or "")
            if section_key in seen_sections:
                # Already fetched this section — find it in map
                for cid, pcontent in parent_content_map.items():
                    other = next((r for r in child_rows if r.id == cid), None)
                    if other and (other.document_id, other.heading or "") == section_key:
                        parent_content_map[row.id] = pcontent
                        break
                continue
            seen_sections.add(section_key)

            siblings = (
                (
                    await db.execute(
                        select(DocumentChunk.content)
                        .where(
                            DocumentChunk.document_id == row.document_id,
                            DocumentChunk.heading == (row.heading or ""),
                            DocumentChunk.deleted_at == None,  # noqa: E711
                        )
                        .order_by(DocumentChunk.chunk_index.asc())
                    )
                )
                .scalars()
                .all()
            )

            parent_text = "\n\n".join(siblings) if siblings else row.content
            parent_content_map[row.id] = parent_text

        # Step C: enrich evidence with parent section content
        for c in evidence:
            parent = parent_content_map.get(c.get("id", ""))
            if parent:
                c["content"] = parent

    # ── 4. Cross-encoder rerank ──
    try:
        await JinaRerankOp()(ctx)
    except Exception:
        logger.warning("JinaRerankOp failed, using retrieval order", exc_info=True)

    # ── 5. CRAG evaluation (quality gate before synthesis) ──
    from src.shared.crag_evaluator import evaluate_results as crag_evaluate

    crag_eval = crag_evaluate(
        query=body.question,
        results=ctx.get("evidence_chunks", []),
        score_key="score",
    )
    crag_verdict = crag_eval.verdict.value

    # ── 6. Synthesize cited answer ──
    ctx["question"] = body.question
    await CitedAnswerOp()(ctx)

    answer_text = ctx.get("answer", "No answer found.")
    raw_citations = ctx.get("citations", [])
    # Use LLM confidence as primary, but floor it if CRAG says INCORRECT
    confidence = ctx.get("confidence", 0.0)
    if crag_verdict == "incorrect" and confidence > 0.3:
        confidence = min(confidence, 0.2)

    citations = [
        CitationRef(
            index=c.get("index"),
            document_id=c.get("document_id", ""),
            chunk_id=c.get("chunk_id"),
            section=c.get("section"),
            page=c.get("page"),
            quote=c.get("quote"),
        )
        for c in raw_citations
    ]

    # ── 6. Log QA interaction ──
    query_hash = _hashlib.sha256(body.question.encode()).hexdigest()[:16]
    qa_log_data = QALogCreate(
        query_text=body.question,
        query_hash=query_hash,
        answer_text=answer_text,
        citations={"refs": raw_citations},
        confidence=confidence,
        crag_verdict=crag_verdict,
        pipeline_used=pipeline,
    )
    qa_log = await qa_log_service.create(db, space_id, qa_log_data)
    await db.commit()
    await db.refresh(qa_log)

    return QAResponse(
        question=body.question,
        answer=answer_text,
        citations=citations,
        confidence=confidence,
        crag_verdict=crag_verdict,
        pipeline_used=pipeline,
        qa_log_id=qa_log.id,
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

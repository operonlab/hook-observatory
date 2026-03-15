"""Memvault routes — REST API endpoints.

Prefix: /api/memvault (mounted in main.py)
"""

import logging
import math
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import BadRequestError, NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from .dedup import DedupDecision, check_duplicate, merge_content
from .embedding import get_embedding
from .injection_guard import is_unsafe_for_injection, sanitize_for_injection
from .schemas import (
    EnhancedSearchResult,
    KnowledgeDomainCreate,
    KnowledgeDomainResponse,
    KnowledgeDomainUpdate,
    MemoryBlockCreate,
    MemoryBlockResponse,
    MemoryBlockUpdate,
    ProfileScoreResponse,
    ProfileScoreUpdate,
    SearchMetadata,
    SemanticSearchParams,  # noqa: F401 — available for future use
    TagResponse,
)
from .services import (
    knowledge_domain_service,
    memory_block_service,
    profile_score_service,
    should_search,
    tag_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["memvault"])


# ======================== Memory Blocks ========================


@router.get("/blocks", response_model=PaginatedResponse[MemoryBlockResponse])
async def list_blocks(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tag: str | None = Query(None, description="Single tag filter"),
    tags: str | None = Query(None, description="Comma-separated tag filter"),
    block_type: str | None = Query(None, description="Block type filter"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    # Support both singular 'tag' and plural 'tags' params
    tag_list = None
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    elif tag:
        tag_list = [tag]

    if tag_list:
        return await memory_block_service.list_by_tags(db, space_id, tag_list, pagination)
    if block_type:
        return await memory_block_service.list_by_type(db, space_id, block_type, pagination)
    return await memory_block_service.list(db, space_id, pagination)


@router.get("/blocks/{block_id}", response_model=MemoryBlockResponse)
async def get_block(
    block_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.read"),
):
    instance = await memory_block_service.get(db, block_id)
    if not instance:
        raise NotFoundError("Block not found", code="memvault.block_not_found")
    return memory_block_service.to_response(instance)


@router.post("/blocks", response_model=MemoryBlockResponse, status_code=201)
async def create_block(
    body: MemoryBlockCreate,
    space_id: str = Query("default"),
    skip_dedup: bool = Query(False, description="Skip dedup check"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.write"),
):
    # G1: Pre-creation dedup check (requires embedding, best-effort)
    try:
        embedding = await get_embedding(body.content, task_type="search_document")
    except Exception:
        logger.warning("Embedding failed for dedup check, skipping", exc_info=True)
        embedding = None

    if embedding and not skip_dedup:
        dedup_result = await check_duplicate(
            db, space_id, body.content, embedding, block_type=body.block_type
        )

        if dedup_result.decision == DedupDecision.SKIP:
            # Near-identical block exists — return existing
            logger.info(
                "Dedup SKIP: %s (existing=%s)",
                dedup_result.reason,
                dedup_result.existing_block_id,
            )
            existing = await memory_block_service.get(db, dedup_result.existing_block_id)
            if existing:
                return memory_block_service.to_response(existing)

        if dedup_result.decision == DedupDecision.MERGE:
            # Merge new content into existing block
            logger.info(
                "Dedup MERGE: %s (existing=%s)",
                dedup_result.reason,
                dedup_result.existing_block_id,
            )
            existing = await memory_block_service.get(db, dedup_result.existing_block_id)
            if existing:
                merged = merge_content(existing.content, body.content)
                from .schemas import MemoryBlockUpdate

                await memory_block_service.update(
                    db,
                    dedup_result.existing_block_id,
                    MemoryBlockUpdate(content=merged),
                )
                # Re-embed with merged content (best-effort)
                try:
                    merged_emb = await get_embedding(merged, task_type="search_document")
                    if merged_emb:
                        await memory_block_service.update_embedding(
                            db, dedup_result.existing_block_id, merged_emb
                        )
                except Exception:
                    logger.warning("Embedding failed for merge, skipping", exc_info=True)
                await db.commit()
                await db.refresh(existing)
                return memory_block_service.to_response(existing)

    # Normal creation path
    instance = await memory_block_service.create(db, space_id, body)
    try:
        if embedding:
            await memory_block_service.update_embedding(db, instance.id, embedding)
    except Exception:
        logger.warning("Failed to store embedding for block %s", instance.id, exc_info=True)
    await db.commit()
    await db.refresh(instance)
    return memory_block_service.to_response(instance)


@router.put("/blocks/{block_id}", response_model=MemoryBlockResponse)
async def update_block(
    block_id: str,
    body: MemoryBlockUpdate,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.write"),
):
    instance = await memory_block_service.update(db, block_id, body)
    if not instance:
        raise NotFoundError("Block not found", code="memvault.block_not_found")
    await db.commit()
    await db.refresh(instance)
    return memory_block_service.to_response(instance)


@router.delete("/blocks/{block_id}", status_code=204)
async def delete_block(
    block_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.write"),
):
    deleted = await memory_block_service.delete(db, block_id)
    if not deleted:
        raise NotFoundError("Block not found", code="memvault.block_not_found")
    await db.commit()


# ======================== Semantic Search ========================


@router.get("/search", response_model=EnhancedSearchResult)
async def search(
    q: str = Query(..., min_length=1, max_length=2000),
    top_k: int = Query(10, ge=1, le=100),
    space_id: str = Query("default"),
    include_metadata: bool = Query(False, description="Include scoring metadata"),
    skip_adaptive: bool = Query(False, description="Force search even if adaptive says skip"),
    scope: str | None = Query(
        None,
        description="Scope filter: global, session:{id}, user:{id}, type:{type}. Comma-separated.",
    ),
    date_from: datetime | None = Query(None, description="Filter: created_at >= date_from"),
    date_to: datetime | None = Query(None, description="Filter: created_at <= date_to"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.read"),
):
    # Phase B2: Adaptive Retrieval
    if not skip_adaptive:
        do_search, reason = should_search(q)
        if not do_search:
            meta = SearchMetadata(
                adaptive_skipped=True,
                adaptive_reason=reason,
                vector_used=False,
                scoring_applied=False,
                input_count=0,
                output_count=0,
                scope=scope,
            )
            return EnhancedSearchResult(
                results=[],
                metadata=meta if include_metadata else None,
            )

    try:
        query_embedding = await get_embedding(q, task_type="search_query")
    except Exception:
        logger.warning("Embedding failed for search query, falling back to text", exc_info=True)
        query_embedding = None
    if query_embedding is None:
        # Fallback: ILIKE text search when Ollama is unavailable
        results = await memory_block_service.text_search(
            db,
            space_id,
            q,
            top_k,
            scope=scope,
            date_from=date_from,
            date_to=date_to,
        )
        meta = SearchMetadata(
            vector_used=False,
            keyword_used=True,
            scoring_applied=False,
            input_count=len(results),
            output_count=len(results),
            scope=scope,
        )
        return EnhancedSearchResult(
            results=results,
            metadata=meta if include_metadata else None,
        )

    # Try Qdrant hybrid search first, fall back to pgvector
    qdrant_result = await memory_block_service.qdrant_search(
        db,
        space_id,
        q,
        query_embedding,
        top_k=top_k,
        scope=scope,
        date_from=date_from,
        date_to=date_to,
    )
    if qdrant_result is not None:
        results, meta = qdrant_result
        return EnhancedSearchResult(
            results=results,
            metadata=meta if include_metadata else None,
        )

    results, meta = await memory_block_service.semantic_search(
        db,
        space_id,
        query_embedding,
        top_k=top_k,
        query=q,
        scope=scope,
        date_from=date_from,
        date_to=date_to,
    )

    # G2: Sanitize results before returning (prevents injection via stored memories)
    for r in results:
        unsafe, reason = is_unsafe_for_injection(r.block.content)
        if unsafe:
            r.block.content = sanitize_for_injection(r.block.content)
            meta.injection_sanitized = (meta.injection_sanitized or 0) + 1

    return EnhancedSearchResult(
        results=results,
        metadata=meta if include_metadata else None,
    )


# ======================== Tags ========================


@router.get("/tags", response_model=list[TagResponse])
async def list_tags(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.read"),
):
    return await tag_service.list_tags(db, space_id)


@router.post("/tags/sync", status_code=200)
async def sync_tags(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.write"),
):
    count = await tag_service.sync_tags(db, space_id)
    await db.commit()
    return {"synced": count}


# ======================== Knowledge Domains ========================


@router.get("/domains", response_model=PaginatedResponse[KnowledgeDomainResponse])
async def list_domains(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.read"),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await knowledge_domain_service.list(db, space_id, pagination)


@router.post("/domains", response_model=KnowledgeDomainResponse, status_code=201)
async def create_domain(
    body: KnowledgeDomainCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.write"),
):
    instance = await knowledge_domain_service.create(db, space_id, body)
    await db.commit()
    return knowledge_domain_service.to_response(instance)


@router.patch("/domains/{domain_id}", response_model=KnowledgeDomainResponse)
async def update_domain(
    domain_id: str,
    body: KnowledgeDomainUpdate,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.write"),
):
    instance = await knowledge_domain_service.update(db, domain_id, body)
    if not instance:
        raise NotFoundError("Domain not found", code="memvault.domain_not_found")
    await db.commit()
    return knowledge_domain_service.to_response(instance)


# ======================== Profile Score ========================


@router.get("/profile", response_model=ProfileScoreResponse)
async def get_profile(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.read"),
):
    profile = await profile_score_service.get_by_space(db, space_id)
    if not profile:
        # Return a default empty profile instead of 404
        return ProfileScoreResponse(
            id="",
            space_id=space_id,
            created_by=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            knowledge_score=0.0,
            attitude_score=0.0,
            skill_score=0.0,
        )
    return profile


@router.put("/profile", response_model=ProfileScoreResponse)
async def upsert_profile(
    body: ProfileScoreUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.write"),
):
    result = await profile_score_service.upsert(db, space_id, body)
    await db.commit()
    return result


@router.post("/profile/recalculate", response_model=ProfileScoreResponse)
async def recalculate_profile(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.write"),
):
    """Recalculate KAS scores from actual KG data."""
    from .kg_models import AttitudeFact, Cluster, SkillInvocation, Triple, WisdomNode

    # Knowledge score: based on triples + clusters + wisdom
    triple_count = (
        await db.execute(
            select(func.count()).select_from(Triple).where(Triple.space_id == space_id)
        )
    ).scalar() or 0
    cluster_count = (
        await db.execute(
            select(func.count()).select_from(Cluster).where(Cluster.space_id == space_id)
        )
    ).scalar() or 0
    wisdom_count = (
        await db.execute(
            select(func.count()).select_from(WisdomNode).where(WisdomNode.space_id == space_id)
        )
    ).scalar() or 0

    # K score: log-scaled, 100 triples = ~50, 1000+ = ~80, + bonus for clusters/wisdom
    k_base = min(math.log10(max(triple_count, 1)) / math.log10(2000) * 70, 70)
    k_cluster_bonus = min(cluster_count * 2, 15)
    k_wisdom_bonus = min(wisdom_count * 2, 15)
    knowledge_score = round(min(k_base + k_cluster_bonus + k_wisdom_bonus, 100), 1)

    # Attitude score: based on attitude count + confidence
    attitude_result = await db.execute(
        select(func.count(), func.avg(AttitudeFact.confidence)).where(
            AttitudeFact.space_id == space_id, AttitudeFact.superseded_by.is_(None)
        )
    )
    att_row = attitude_result.one()
    att_count = att_row[0] or 0
    att_avg_conf = att_row[1] or 0.0
    a_base = min(math.log10(max(att_count, 1)) / math.log10(500) * 60, 60)
    a_conf_bonus = att_avg_conf * 40
    attitude_score = round(min(a_base + a_conf_bonus, 100), 1)

    # Skill score: based on invocations + success rate + unique skills
    skill_result = await db.execute(
        select(
            func.count(),
            func.count(func.distinct(SkillInvocation.skill_name)),
            func.avg(case((SkillInvocation.outcome == "success", 1.0), else_=0.0)),
        ).where(SkillInvocation.space_id == space_id)
    )
    skill_row = skill_result.one()
    inv_count = skill_row[0] or 0
    unique_skills = skill_row[1] or 0
    avg_success = skill_row[2] or 0.0
    s_base = min(math.log10(max(inv_count, 1)) / math.log10(500) * 50, 50)
    s_variety_bonus = min(unique_skills * 2, 25)
    s_success_bonus = avg_success * 25
    skill_score = round(min(s_base + s_variety_bonus + s_success_bonus, 100), 1)

    # Upsert profile
    result = await profile_score_service.upsert(
        db,
        space_id,
        ProfileScoreUpdate(
            knowledge_score=knowledge_score,
            attitude_score=attitude_score,
            skill_score=skill_score,
        ),
    )
    await db.commit()
    return result


# ======================== Sync ========================


@router.get("/sync/stats")
async def sync_stats(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Return extraction stats based on DB data.

    Counts distinct source_sessions across blocks and triples to show
    how many sessions have been successfully ingested.
    """
    from .kg_models import Triple
    from .models import MemoryBlock

    await db.execute(
        select(func.count(func.distinct(MemoryBlock.source_session))).where(
            MemoryBlock.space_id == space_id, MemoryBlock.source_session.isnot(None)
        )
    )

    await db.execute(
        select(func.count(func.distinct(Triple.source_session))).where(
            Triple.space_id == space_id, Triple.source_session.isnot(None)
        )
    )

    # Union of unique sessions across both tables
    from sqlalchemy import union

    block_q = select(MemoryBlock.source_session).where(
        MemoryBlock.space_id == space_id, MemoryBlock.source_session.isnot(None)
    )
    triple_q = select(Triple.source_session).where(
        Triple.space_id == space_id, Triple.source_session.isnot(None)
    )
    combined = union(block_q, triple_q).subquery()
    total_synced = (await db.execute(select(func.count()).select_from(combined))).scalar() or 0

    return {
        "total": total_synced,
        "synced": total_synced,
        "failed": 0,
        "skipped": 0,
    }


@router.post("/sync/scan")
async def sync_scan():
    """Session extraction is handled automatically by the SessionEnd hook pipeline.

    This endpoint returns a stub result. Use extract-v2-async.sh hook for live extraction.
    """
    return {
        "total": 0,
        "synced": 0,
        "failed": 0,
        "skipped": 0,
        "already": 0,
        "log": "Session extraction is handled automatically by SessionEnd hook pipeline.",
    }


# ======================== Reflection (G5) ========================


@router.post("/reflect")
async def reflect_session(
    session_id: str = Query(..., description="Session ID to reflect on"),
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("memvault.read"),
):
    """G5: Extract invariants and derived insights from a session's memories."""
    # Fetch blocks from this session
    from .models import MemoryBlock
    from .reflection import format_reflection_for_injection, reflect_on_session

    q = (
        select(MemoryBlock)
        .where(
            MemoryBlock.space_id == space_id,
            MemoryBlock.source_session == session_id,
            MemoryBlock.deleted_at == None,  # noqa: E711
        )
        .order_by(MemoryBlock.created_at)
    )
    rows = (await db.execute(q)).scalars().all()

    blocks = [
        {
            "content": r.content,
            "block_type": r.block_type,
            "tags": r.tags or [],
        }
        for r in rows
    ]

    result = reflect_on_session(blocks, session_id=session_id)

    return {
        "session_id": session_id,
        "block_count": result.block_count,
        "invariants": result.invariants,
        "derived": result.derived,
        "formatted": format_reflection_for_injection(result),
        "reflected_at": result.reflected_at.isoformat(),
    }


# ======================== Status ========================


@router.get("/status")
async def memvault_status():
    return {"module": "memvault", "status": "active", "phase": "A"}


# ======================== Frozen Tier (Thaw) ========================


@router.get("/frozen", summary="List frozen blocks")
async def list_frozen_blocks(
    space_id: str = Query("default"),
    block_type: str | None = Query(None),
    tag: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List frozen block metadata (no content -- needs thaw)."""
    from .models import BlockFrozen

    q = select(BlockFrozen).where(
        BlockFrozen.space_id == space_id,
    )
    if block_type:
        q = q.where(BlockFrozen.block_type == block_type)
    if tag:
        q = q.where(BlockFrozen.tags.contains([tag]))

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.order_by(BlockFrozen.frozen_at.desc())
    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    return {
        "items": [
            {
                "id": r.id,
                "space_id": r.space_id,
                "created_at": r.created_at,
                "frozen_at": r.frozen_at,
                "block_type": r.block_type,
                "tags": r.tags or [],
                "summary": r.summary,
                "content_size": r.content_size,
                "tier": "frozen",
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/frozen/{block_id}/thaw",
    summary="Thaw frozen block",
)
async def thaw_frozen_block(
    block_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Fetch full content from S3 for a frozen block.

    May take 1-3s for S3 download + decompression.
    """
    import json

    from src.shared.storage import (
        compute_content_hash,
        download_and_decompress,
    )

    from .models import BlockFrozen

    q = select(BlockFrozen).where(BlockFrozen.id == block_id)
    frozen = (await db.execute(q)).scalar_one_or_none()
    if not frozen:
        raise NotFoundError(
            f"Frozen block {block_id} not found",
            code="memvault.frozen_not_found",
        )

    data = await download_and_decompress(frozen.s3_uri)
    if data is None:
        raise BadRequestError(
            "Failed to retrieve frozen content from S3",
            code="memvault.thaw_failed",
        )

    # Verify integrity
    actual_hash = compute_content_hash(data)
    if actual_hash != frozen.content_hash:
        raise BadRequestError(
            f"Content hash mismatch: expected {frozen.content_hash}, got {actual_hash}",
            code="memvault.integrity_error",
        )

    content = json.loads(data.decode("utf-8"))
    return {
        "id": block_id,
        "content": content,
        "tier": "frozen",
        "frozen_at": frozen.frozen_at,
    }

"""Memvault KG routes — Knowledge Graph API endpoints.

Prefix: /api/memvault/kg (mounted via __init__.py)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.shared.deps import get_db
from src.shared.errors import NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from .embedding import get_embedding, get_embeddings_batch
from .entity_resolution import entity_resolution_service, normalize_entity_text
from .kg_schemas import (
    AttitudeEvolveRequest,
    AttitudeEvolveResult,
    AttitudeFactCreate,
    AttitudeFactResponse,
    CascadeRecallResult,
    CommunityDetail,
    CommunityRegenerateRequest,
    CommunityResponse,
    CommunitySummaryRegenerateRequest,
    CommunitySummaryResponse,
    EntityCanonicalResponse,
    EntityMergeRequest,
    EntityMergeResult,
    EntityResolutionStats,
    GraphTraversalResult,
    SkillInvocationCreate,
    SkillInvocationResponse,
    SkillProficiencyResponse,
    TripleBatchCreate,
    TripleCreate,
    TripleInvalidateRequest,
    TripleResponse,
)
from .kg_services import (
    attitude_service,
    cascade_recall_service,
    community_service,
    community_summary_service,
    confidence_decay_service,
    graph_traversal_service,
    skill_tracking_service,
    triple_service,
)

router = APIRouter(prefix="/kg", tags=["memvault-kg"])


# ======================== Triples ========================


@router.post("/triples", response_model=TripleResponse, status_code=201)
async def create_triple(
    body: TripleCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    instance = await triple_service.create(db, space_id, body)
    # Generate embedding (best-effort)
    embedding_text = f"{instance.subject} {instance.predicate} {instance.object}"
    embedding = await get_embedding(embedding_text)
    if embedding:
        instance.embedding = embedding
        await db.flush()
    await db.commit()
    await db.refresh(instance)
    return triple_service.to_response(instance)


@router.post("/triples/batch", status_code=201)
async def batch_ingest_triples(
    body: TripleBatchCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    created = await triple_service.batch_ingest(db, space_id, body)
    await db.commit()
    return {"ingested": len(created), "session_id": body.session_id}


@router.get("/triples", response_model=PaginatedResponse[TripleResponse])
async def list_triples(
    space_id: str = Query("default"),
    predicate: str | None = Query(None),
    subject: str | None = Query(None),
    include_invalid: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    if predicate:
        results = await triple_service.search_by_predicate(
            db,
            space_id,
            predicate,
            subject=subject,
            include_invalid=include_invalid,
        )
        return PaginatedResponse(
            items=results,
            total=len(results),
            page=page,
            page_size=page_size,
        )
    pagination = PaginationParams(page=page, page_size=page_size)
    return await triple_service.list(db, space_id, pagination)


@router.get("/triples/search", response_model=list[TripleResponse])
async def search_triples(
    q: str = Query(..., min_length=1, max_length=2000),
    top_k: int = Query(10, ge=1, le=100),
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    query_embedding = await get_embedding(q)
    if query_embedding:
        return await triple_service.semantic_search(db, space_id, query_embedding, top_k=top_k)
    # Text fallback when Ollama is unavailable
    return await triple_service.search_by_predicate(db, space_id, q, limit=top_k)


@router.delete("/triples/{triple_id}", status_code=204)
async def delete_triple(
    triple_id: str,
    db: AsyncSession = Depends(get_db),
):
    await triple_service.delete_by_id(db, triple_id)
    await db.commit()
    return None


@router.put("/triples/{triple_id}", response_model=TripleResponse)
async def update_triple(
    triple_id: str,
    body: TripleCreate,
    db: AsyncSession = Depends(get_db),
):
    instance = await triple_service.update_by_id(db, triple_id, body)
    await db.commit()
    await db.refresh(instance)
    return triple_service.to_response(instance)


@router.put("/triples/{triple_id}/invalidate", response_model=TripleResponse)
async def invalidate_triple(
    triple_id: str,
    body: TripleInvalidateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Mark a triple as invalid (soft temporal invalidation)."""
    instance = await triple_service.invalidate(
        db,
        triple_id,
        reason=body.reason,
        replacement_id=body.replacement_triple_id,
    )
    await db.commit()
    await db.refresh(instance)
    return triple_service.to_response(instance)


# ======================== Communities ========================


@router.get("/communities", response_model=list[CommunityResponse])
async def list_communities(
    space_id: str = Query("default"),
    resolution_level: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await community_service.list_communities(db, space_id, resolution_level=resolution_level)


@router.get("/communities/{community_id}", response_model=CommunityDetail)
async def get_community(
    community_id: str,
    db: AsyncSession = Depends(get_db),
):
    detail = await community_service.get_community_detail(db, community_id)
    if not detail:
        raise NotFoundError("Community not found", code="memvault.community_not_found")
    return detail


@router.post("/communities/regenerate", status_code=200)
async def regenerate_communities(
    body: CommunityRegenerateRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Accept community data from community_pipeline.py and save atomically.

    Converts pipeline format (triples with id) to service format (members with triple_id).
    """
    communities_for_service = []
    generation_batch = body.generated_at

    for c in body.communities:
        triple_ids = []
        for t in c.get("triples", []):
            triple_id = t.get("id", "")
            if triple_id:
                triple_ids.append(triple_id)

        communities_for_service.append(
            {
                "name": c.get("name", ""),
                "resolution_level": c.get("resolution_level", 0),
                "size": c.get("size", 0),
                "entity_ids": c.get("entity_ids"),
                "top_entities": c.get("top_entities"),
                "top_predicates": c.get("top_predicates"),
                "summary": c.get("summary"),
                "parent_community_id": c.get("parent_community_id"),
                "modularity_score": c.get("modularity_score"),
                "generation_batch": generation_batch,
                "triple_ids": triple_ids,
            }
        )

    saved = await community_service.save_communities(db, space_id, communities_for_service)
    await db.commit()
    return {"saved": saved, "generation_batch": generation_batch}


# ======================== Community Summaries ========================


@router.get("/summaries", response_model=list[CommunitySummaryResponse])
async def list_summaries(
    space_id: str = Query("default"),
    resolution_level: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await community_summary_service.list_summaries(
        db, space_id, resolution_level=resolution_level
    )


@router.post("/summaries/regenerate", status_code=200)
async def regenerate_summaries(
    body: CommunitySummaryRegenerateRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Accept community summary data from community_summary_pipeline.py and save atomically."""
    saved = await community_summary_service.save_summaries(db, space_id, body.summaries)
    await db.commit()
    return {"saved": saved, "generated_at": body.generated_at}


# ======================== Attitude ========================


@router.get("/attitudes", response_model=list[AttitudeFactResponse])
async def list_attitudes(
    space_id: str = Query("default"),
    category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await attitude_service.get_current(db, space_id, category=category)


@router.post("/attitudes", response_model=AttitudeFactResponse, status_code=201)
async def create_attitude(
    body: AttitudeFactCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    instance = await attitude_service.create_fact(db, space_id, body)
    await db.commit()
    await db.refresh(instance)
    return attitude_service.to_response(instance)


@router.post("/attitudes/evolve", response_model=AttitudeEvolveResult)
async def evolve_attitude(
    body: AttitudeEvolveRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    result = await attitude_service.evolve(db, space_id, body)
    await db.commit()
    return result


@router.get("/attitudes/history/{fact_id}", response_model=list[AttitudeFactResponse])
async def attitude_history(
    fact_id: str,
    db: AsyncSession = Depends(get_db),
):
    return await attitude_service.get_history(db, fact_id)


@router.delete("/attitudes/{fact_id}", status_code=204)
async def delete_attitude(
    fact_id: str,
    db: AsyncSession = Depends(get_db),
):
    await attitude_service.delete_by_id(db, fact_id)
    await db.commit()
    return None


@router.put("/attitudes/{fact_id}", response_model=AttitudeFactResponse)
async def update_attitude(
    fact_id: str,
    body: AttitudeFactCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    instance = await attitude_service.update_by_id(db, fact_id, body)
    await db.commit()
    await db.refresh(instance)
    return attitude_service.to_response(instance)


# ======================== Skill Tracking ========================


@router.post("/skills/invoke", response_model=SkillInvocationResponse, status_code=201)
async def record_skill_invocation(
    body: SkillInvocationCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    instance = await skill_tracking_service.record_invocation(db, space_id, body)
    await db.commit()
    await db.refresh(instance)
    return skill_tracking_service.to_response(instance)


@router.get("/skills/proficiency", response_model=list[SkillProficiencyResponse])
async def get_proficiency(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    return await skill_tracking_service.get_proficiency(db, space_id)


@router.get("/skills/{skill_name}/history", response_model=list[SkillInvocationResponse])
async def skill_history(
    skill_name: str,
    space_id: str = Query("default"),
    limit: int = Query(20),
    db: AsyncSession = Depends(get_db),
):
    return await skill_tracking_service.get_skill_history(db, space_id, skill_name, limit=limit)


@router.delete("/skills/invocations/{invocation_id}", status_code=204)
async def delete_skill_invocation(
    invocation_id: str,
    db: AsyncSession = Depends(get_db),
):
    await skill_tracking_service.delete_by_id(db, invocation_id)
    await db.commit()
    return None


# ======================== Cascade Recall ========================


@router.get("/recall", response_model=CascadeRecallResult)
async def cascade_recall(
    q: str = Query(..., min_length=1, max_length=2000),
    top_k: int = Query(5, ge=1, le=20),
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    return await cascade_recall_service.recall(db, space_id, q, top_k=top_k)


# ======================== Confidence Decay ========================


@router.post("/decay", status_code=200)
async def apply_confidence_decay(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Apply exponential confidence decay to all current attitude facts in the space.

    Designed to be called periodically (e.g., weekly via cron/launchd).
    Returns counts of facts checked and updated.
    """
    result = await confidence_decay_service.apply_decay(db, space_id)
    await db.commit()
    return result


# ======================== Embedding Backfill ========================


# ======================== Entity Resolution ========================


@router.get("/entities", response_model=PaginatedResponse[EntityCanonicalResponse])
async def list_entities(
    space_id: str = Query("default"),
    entity_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List canonical entities with optional type filter."""
    from sqlalchemy import func, select

    from .kg_models import EntityCanonical

    q = select(EntityCanonical).where(
        EntityCanonical.space_id == space_id,
        EntityCanonical.deleted_at.is_(None),
    )
    if entity_type:
        q = q.where(EntityCanonical.entity_type == entity_type)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    q = q.order_by(EntityCanonical.canonical_name).offset((page - 1) * page_size).limit(page_size)
    entities = (await db.execute(q)).scalars().all()

    return PaginatedResponse(
        items=[entity_resolution_service.to_response(e) for e in entities],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/entities/stats", response_model=EntityResolutionStats)
async def entity_stats(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Get entity resolution statistics."""
    return await entity_resolution_service.get_stats(db, space_id)


@router.get(
    "/entities/merge-candidates",
    response_model=list[dict],
)
async def entity_merge_candidates(
    space_id: str = Query("default"),
    threshold: float = Query(0.92, ge=0.5, le=1.0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Find entities that are candidates for merging (high embedding similarity)."""
    candidates = await entity_resolution_service.find_merge_candidates(
        db,
        space_id,
        threshold=threshold,
        limit=limit,
    )
    return [
        {"primary": a.model_dump(), "secondary": b.model_dump(), "similarity": sim}
        for a, b, sim in candidates
    ]


@router.post("/entities/merge", response_model=EntityMergeResult)
async def merge_entities(
    body: EntityMergeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Merge secondary entity into primary."""
    result = await entity_resolution_service.merge_entities(
        db,
        body.primary_id,
        body.secondary_id,
    )
    await db.commit()
    return result


@router.post("/entities/backfill", status_code=200)
async def backfill_entity_resolution(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Backfill entity resolution for triples missing canonical IDs."""
    from sqlalchemy import select

    from .kg_models import Triple

    q = select(Triple).where(
        Triple.space_id == space_id,
        Triple.deleted_at.is_(None),
        Triple.canonical_subject_id.is_(None),
    )
    triples = list((await db.execute(q)).scalars().all())
    resolved = await entity_resolution_service.batch_resolve_triples(db, space_id, triples)
    await db.commit()
    return {"total_unresolved": len(triples), "resolved": resolved}


@router.post("/entities/auto-merge", status_code=200)
async def auto_merge_entities(
    space_id: str = Query("default"),
    threshold: float = Query(0.95, ge=0.85, le=1.0),
    max_merges: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Auto-merge entity pairs above similarity threshold."""
    results = await entity_resolution_service.auto_merge(
        db, space_id, threshold=threshold, max_merges=max_merges
    )
    await db.commit()
    return {
        "merged": len(results),
        "details": [
            {
                "canonical_name": r.canonical_name,
                "aliases": r.aliases,
                "triples_updated": r.triples_updated,
            }
            for r in results
        ],
    }


# ======================== Graph Traversal ========================


@router.get("/traverse", response_model=GraphTraversalResult)
async def graph_traverse(
    entity: str = Query(..., min_length=1, max_length=500),
    space_id: str = Query("default"),
    max_depth: int = Query(2, ge=1, le=4),
    direction: str = Query("both", pattern="^(outgoing|incoming|both)$"),
    predicates: str | None = Query(None, description="Comma-separated predicate filter"),
    max_results: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Multi-hop graph traversal from a seed entity using recursive CTE."""
    entity = normalize_entity_text(entity)
    predicate_filter = (
        [p.strip() for p in predicates.split(",") if p.strip()] if predicates else None
    )
    return await graph_traversal_service.traverse(
        db,
        space_id,
        entity,
        max_depth=max_depth,
        direction=direction,
        predicate_filter=predicate_filter,
        max_results=max_results,
    )


# ======================== Embedding Backfill ========================


@router.post("/embeddings/backfill", status_code=200)
async def backfill_embeddings(
    space_id: str = Query("default"),
    batch_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Backfill missing embeddings for triples and attitude_facts.

    Processes in batches via Ollama nomic-embed-text. Designed for one-shot
    migration backfill or periodic catch-up.
    """
    from sqlalchemy import select

    from .kg_models import AttitudeFact, Triple

    # --- Triples ---
    triple_q = (
        select(Triple)
        .where(Triple.space_id == space_id, Triple.embedding.is_(None))
        .order_by(Triple.created_at)
    )
    result = await db.execute(triple_q)
    triples = list(result.scalars().all())

    triple_updated = 0
    for i in range(0, len(triples), batch_size):
        batch = triples[i : i + batch_size]
        texts = [f"{t.subject} {t.predicate} {t.object}" for t in batch]
        embeddings = await get_embeddings_batch(texts)
        for t, emb in zip(batch, embeddings, strict=True):
            if emb:
                t.embedding = emb
                triple_updated += 1
        await db.flush()

    # --- Attitude Facts ---
    attitude_q = (
        select(AttitudeFact)
        .where(AttitudeFact.space_id == space_id, AttitudeFact.embedding.is_(None))
        .order_by(AttitudeFact.created_at)
    )
    result = await db.execute(attitude_q)
    attitudes = list(result.scalars().all())

    attitude_updated = 0
    for i in range(0, len(attitudes), batch_size):
        batch = attitudes[i : i + batch_size]
        texts = [f"{a.category}: {a.fact}" for a in batch]
        embeddings = await get_embeddings_batch(texts)
        for a, emb in zip(batch, embeddings, strict=True):
            if emb:
                a.embedding = emb
                attitude_updated += 1
        await db.flush()

    await db.commit()
    return {
        "triples": {"total_missing": len(triples), "updated": triple_updated},
        "attitudes": {"total_missing": len(attitudes), "updated": attitude_updated},
    }


# ======================== Session Context (Gap 2: Block ↔ Triple Bridge) ========================


@router.get("/session-context")
async def get_session_context(
    source_session: str = Query(..., min_length=1, max_length=200),
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Return all blocks, triples, and entities for a given source_session.

    Bridges the two parallel outputs (blocks + triples) that share the
    same source_session, enabling unified session context retrieval.
    """
    from sqlalchemy import select

    from .kg_models import EntityCanonical, Triple
    from .models import MemoryBlock

    # Blocks for this session
    block_q = (
        select(MemoryBlock)
        .where(
            MemoryBlock.space_id == space_id,
            MemoryBlock.source_session == source_session,
            MemoryBlock.deleted_at.is_(None),
        )
        .order_by(MemoryBlock.created_at)
    )
    blocks = (await db.execute(block_q)).scalars().all()

    # Triples for this session
    triple_q = (
        select(Triple)
        .where(
            Triple.space_id == space_id,
            Triple.source_session == source_session,
            Triple.deleted_at.is_(None),
        )
        .order_by(Triple.created_at)
    )
    triples = (await db.execute(triple_q)).scalars().all()

    # Collect canonical entity IDs from triples
    entity_ids = set()
    for t in triples:
        if t.canonical_subject_id:
            entity_ids.add(t.canonical_subject_id)
        if t.canonical_object_id:
            entity_ids.add(t.canonical_object_id)

    entities = []
    if entity_ids:
        entity_q = select(EntityCanonical).where(
            EntityCanonical.id.in_(entity_ids),
            EntityCanonical.deleted_at.is_(None),
        )
        entities = (await db.execute(entity_q)).scalars().all()

    return {
        "source_session": source_session,
        "space_id": space_id,
        "blocks": [
            {
                "id": b.id,
                "content": b.content,
                "block_type": b.block_type,
                "tags": b.tags or [],
                "confidence": b.confidence or 0.0,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in blocks
        ],
        "triples": [
            {
                "id": t.id,
                "subject": t.subject,
                "predicate": t.predicate,
                "object": t.object,
                "invalid_at": t.invalid_at.isoformat() if t.invalid_at else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in triples
        ],
        "entities": [
            {
                "id": e.id,
                "canonical_name": e.canonical_name,
                "aliases": e.aliases or [],
                "entity_type": e.entity_type or "concept",
                "merge_count": e.merge_count or 1,
            }
            for e in entities
        ],
        "summary": {
            "total_blocks": len(blocks),
            "total_triples": len(triples),
            "total_entities": len(entities),
        },
    }


# =============== Intelligence Event Publish (Gap 3: Station → Core) ===============


@router.post("/intelligence/ingest", status_code=200)
async def ingest_intelligence_digest(
    space_id: str = Query("default"),
    digest_type: str = Query("weekly", pattern="^(daily|weekly)$"),
    period: str = Query("", description="Period label, e.g., '2026-W11'"),
    content: str = Query(..., min_length=10),
    db: AsyncSession = Depends(get_db),
):
    """HTTP bridge for session-intelligence station to push digests into Core.

    Publishes a SessionIntelligenceEvents.DIGEST_COMPLETED event, which the
    memvault event handler stores as a knowledge block + auto-extracts KG triples.
    """
    from src.events.types import SessionIntelligenceEvents

    await event_bus.publish(
        Event(
            type=SessionIntelligenceEvents.DIGEST_COMPLETED,
            data={
                "space_id": space_id,
                "digest_type": digest_type,
                "period": period,
                "content": content,
                "tags": ["intelligence", "digest", digest_type],
            },
            source="session-intelligence",
        )
    )

    return {
        "status": "ingested",
        "digest_type": digest_type,
        "period": period,
        "space_id": space_id,
    }

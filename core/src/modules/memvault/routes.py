"""Memvault routes — REST API endpoints.

Prefix: /api/memvault (mounted in main.py)
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db
from src.shared.errors import NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from .schemas import (
    KASProfileResponse,
    KASProfileUpdate,
    KnowledgeDomainCreate,
    KnowledgeDomainResponse,
    KnowledgeDomainUpdate,
    MemoryBlockCreate,
    MemoryBlockResponse,
    MemoryBlockUpdate,
    SemanticSearchParams,  # noqa: F401 — available for future use
    SemanticSearchResult,
    TagResponse,
)
from .services import (
    kas_profile_service,
    knowledge_domain_service,
    memory_block_service,
    tag_service,
)

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
):
    instance = await memory_block_service.get(db, block_id)
    if not instance:
        raise NotFoundError("Block not found", code="memvault.block_not_found")
    return memory_block_service.to_response(instance)


@router.post("/blocks", response_model=MemoryBlockResponse, status_code=201)
async def create_block(
    body: MemoryBlockCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    instance = await memory_block_service.create(db, space_id, body)
    await db.commit()
    return memory_block_service.to_response(instance)


@router.patch("/blocks/{block_id}", response_model=MemoryBlockResponse)
async def update_block(
    block_id: str,
    body: MemoryBlockUpdate,
    db: AsyncSession = Depends(get_db),
):
    instance = await memory_block_service.update(db, block_id, body)
    if not instance:
        raise NotFoundError("Block not found", code="memvault.block_not_found")
    await db.commit()
    return memory_block_service.to_response(instance)


@router.delete("/blocks/{block_id}", status_code=204)
async def delete_block(
    block_id: str,
    db: AsyncSession = Depends(get_db),
):
    deleted = await memory_block_service.delete(db, block_id)
    if not deleted:
        raise NotFoundError("Block not found", code="memvault.block_not_found")
    await db.commit()


# ======================== Semantic Search ========================


@router.get("/search", response_model=list[SemanticSearchResult])
async def semantic_search(
    q: str = Query(..., min_length=1, max_length=2000),
    top_k: int = Query(10, ge=1, le=100),
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    # TODO: integrate EmbeddingService to convert query text → vector
    # Placeholder: return empty results until EmbeddingService is ready
    return []


# ======================== Tags ========================


@router.get("/tags", response_model=list[TagResponse])
async def list_tags(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    return await tag_service.list_tags(db, space_id)


@router.post("/tags/sync", status_code=200)
async def sync_tags(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    count = await tag_service.sync_tags(db, space_id)
    await db.commit()
    return {"synced": count}


# ======================== Knowledge Domains ========================


@router.get(
    "/domains", response_model=PaginatedResponse[KnowledgeDomainResponse]
)
async def list_domains(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    return await knowledge_domain_service.list(db, space_id, pagination)


@router.post(
    "/domains", response_model=KnowledgeDomainResponse, status_code=201
)
async def create_domain(
    body: KnowledgeDomainCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    instance = await knowledge_domain_service.create(db, space_id, body)
    await db.commit()
    return knowledge_domain_service.to_response(instance)


@router.patch(
    "/domains/{domain_id}", response_model=KnowledgeDomainResponse
)
async def update_domain(
    domain_id: str,
    body: KnowledgeDomainUpdate,
    db: AsyncSession = Depends(get_db),
):
    instance = await knowledge_domain_service.update(db, domain_id, body)
    if not instance:
        raise NotFoundError("Domain not found", code="memvault.domain_not_found")
    await db.commit()
    return knowledge_domain_service.to_response(instance)


# ======================== KAS Profile ========================


@router.get("/profile", response_model=KASProfileResponse)
async def get_profile(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    profile = await kas_profile_service.get_by_space(db, space_id)
    if not profile:
        # Return a default empty profile instead of 404
        return KASProfileResponse(
            id="",
            space_id=space_id,
            created_by=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            knowledge_score=0.0,
            attitude_score=0.0,
            skill_score=0.0,
        )
    return profile


@router.put("/profile", response_model=KASProfileResponse)
async def upsert_profile(
    body: KASProfileUpdate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    result = await kas_profile_service.upsert(db, space_id, body)
    await db.commit()
    return result


# ======================== Status ========================


@router.get("/status")
async def memvault_status():
    return {"module": "memvault", "status": "active", "phase": "A"}

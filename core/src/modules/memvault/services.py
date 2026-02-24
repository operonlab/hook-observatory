"""Memvault services — CRUD + semantic search.

This is the PUBLIC API of the memvault module.
Other modules import from here, never from models.py.
"""

from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.events.types import MemvaultEvents
from src.shared.errors import BadRequestError, NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService

from .models import EMBEDDING_DIM, KASProfile, KnowledgeDomain, MemoryBlock, Tag
from .schemas import (
    BLOCK_TYPES,
    KASProfileResponse,
    KASProfileUpdate,
    KnowledgeDomainCreate,
    KnowledgeDomainResponse,
    KnowledgeDomainUpdate,
    MemoryBlockCreate,
    MemoryBlockResponse,
    MemoryBlockUpdate,
    SemanticSearchResult,
    TagResponse,
)


# ======================== MemoryBlock Service ========================


class MemoryBlockService(
    BaseCRUDService[MemoryBlock, MemoryBlockCreate, MemoryBlockUpdate, MemoryBlockResponse]
):
    model = MemoryBlock

    def before_create(self, data: MemoryBlockCreate, **kwargs: Any) -> dict:
        d = data.model_dump()
        if d["block_type"] not in BLOCK_TYPES:
            raise BadRequestError(
                f"Invalid block_type: {d['block_type']}",
                code="memvault.invalid_block_type",
            )
        return d

    def after_create(self, instance: MemoryBlock) -> None:
        event_bus.publish(
            Event(
                type=MemvaultEvents.MEMORY_STORED,
                data={"block_id": instance.id, "block_type": instance.block_type},
                source="memvault",
                user_id=instance.created_by,
            )
        )

    def to_response(self, instance: MemoryBlock) -> MemoryBlockResponse:
        return MemoryBlockResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            content=instance.content,
            block_type=instance.block_type,
            tags=instance.tags or [],
            source_session=instance.source_session,
            confidence=instance.confidence or 0.0,
        )

    async def list_by_tags(
        self,
        db: AsyncSession,
        space_id: str,
        tags: list[str],
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[MemoryBlockResponse]:
        """List blocks that contain ALL specified tags."""
        p = pagination or PaginationParams()
        base = select(MemoryBlock).where(
            MemoryBlock.space_id == space_id,
            MemoryBlock.tags.contains(tags),
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = base.offset((p.page - 1) * p.page_size).limit(p.page_size)
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[MemoryBlockResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def list_by_type(
        self,
        db: AsyncSession,
        space_id: str,
        block_type: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[MemoryBlockResponse]:
        """List blocks filtered by block_type."""
        p = pagination or PaginationParams()
        base = select(MemoryBlock).where(
            MemoryBlock.space_id == space_id,
            MemoryBlock.block_type == block_type,
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = base.offset((p.page - 1) * p.page_size).limit(p.page_size)
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[MemoryBlockResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def semantic_search(
        self,
        db: AsyncSession,
        space_id: str,
        query_embedding: list[float],
        top_k: int = 10,
        threshold: float = 0.5,
        tags: list[str] | None = None,
        block_type: str | None = None,
    ) -> list[SemanticSearchResult]:
        """Vector similarity search using pgvector cosine distance."""
        if len(query_embedding) != EMBEDDING_DIM:
            raise BadRequestError(
                f"Embedding must be {EMBEDDING_DIM}d, got {len(query_embedding)}d",
                code="memvault.invalid_embedding_dim",
            )

        # Cosine distance: 1 - similarity. Lower = more similar.
        distance = MemoryBlock.embedding.cosine_distance(query_embedding)
        similarity = (1 - distance).label("similarity")

        q = (
            select(MemoryBlock, similarity)
            .where(
                MemoryBlock.space_id == space_id,
                MemoryBlock.embedding.isnot(None),
                distance < (1 - threshold),  # filter by threshold
            )
            .order_by(distance)
            .limit(top_k)
        )

        if tags:
            q = q.where(MemoryBlock.tags.contains(tags))
        if block_type:
            q = q.where(MemoryBlock.block_type == block_type)

        rows = (await db.execute(q)).all()
        return [
            SemanticSearchResult(
                block=self.to_response(row.MemoryBlock),
                score=round(float(row.similarity), 4),
            )
            for row in rows
        ]

    async def update_embedding(
        self, db: AsyncSession, block_id: str, embedding: list[float]
    ) -> None:
        """Set or update the embedding vector for a block."""
        if len(embedding) != EMBEDDING_DIM:
            raise BadRequestError(
                f"Embedding must be {EMBEDDING_DIM}d",
                code="memvault.invalid_embedding_dim",
            )
        result = await db.execute(
            update(MemoryBlock)
            .where(MemoryBlock.id == block_id)
            .values(embedding=embedding)
        )
        if result.rowcount == 0:
            raise NotFoundError("Block not found", code="memvault.block_not_found")


# ======================== Tag Service ========================


class TagService:
    """Lightweight tag aggregation — no BaseCRUD needed."""

    async def list_tags(
        self, db: AsyncSession, space_id: str
    ) -> list[TagResponse]:
        """List all tags for a space, ordered by usage count."""
        q = (
            select(Tag)
            .where(Tag.space_id == space_id)
            .order_by(Tag.usage_count.desc())
        )
        rows = (await db.execute(q)).scalars().all()
        return [TagResponse(name=r.name, usage_count=r.usage_count) for r in rows]

    async def sync_tags(self, db: AsyncSession, space_id: str) -> int:
        """Rebuild tag counts from blocks. Returns number of tags synced."""
        # Unnest all tags from blocks and count
        tag_counts = (
            select(
                func.unnest(MemoryBlock.tags).label("tag_name"),
                func.count().label("cnt"),
            )
            .where(MemoryBlock.space_id == space_id)
            .group_by(text("tag_name"))
            .subquery()
        )

        # Delete existing tags for this space
        await db.execute(delete(Tag).where(Tag.space_id == space_id))

        # Insert fresh counts
        rows = (await db.execute(select(tag_counts))).all()
        for row in rows:
            db.add(Tag(space_id=space_id, name=row.tag_name, usage_count=row.cnt))
        await db.flush()
        return len(rows)


# ======================== KnowledgeDomain Service ========================


class KnowledgeDomainService(
    BaseCRUDService[
        KnowledgeDomain,
        KnowledgeDomainCreate,
        KnowledgeDomainUpdate,
        KnowledgeDomainResponse,
    ]
):
    model = KnowledgeDomain

    def to_response(self, instance: KnowledgeDomain) -> KnowledgeDomainResponse:
        return KnowledgeDomainResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            name=instance.name,
            description=instance.description,
            maturity=instance.maturity,
            block_count=instance.block_count,
        )


# ======================== KASProfile Service ========================


class KASProfileService:
    """Single KAS profile per space — flat scores."""

    async def get_by_space(
        self, db: AsyncSession, space_id: str
    ) -> KASProfileResponse | None:
        q = select(KASProfile).where(KASProfile.space_id == space_id)
        instance = (await db.execute(q)).scalar_one_or_none()
        if not instance:
            return None
        return KASProfileResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            knowledge_score=instance.knowledge_score,
            attitude_score=instance.attitude_score,
            skill_score=instance.skill_score,
        )

    async def upsert(
        self,
        db: AsyncSession,
        space_id: str,
        data: KASProfileUpdate,
        user_id: str | None = None,
    ) -> KASProfileResponse:
        q = select(KASProfile).where(KASProfile.space_id == space_id)
        existing = (await db.execute(q)).scalar_one_or_none()
        if existing:
            updates = data.model_dump(exclude_unset=True)
            for key, value in updates.items():
                setattr(existing, key, value)
            await db.flush()
            await db.refresh(existing)  # reload server-side onupdate fields
            return self.to_response(existing)
        # Create new
        profile = KASProfile(
            space_id=space_id,
            created_by=user_id,
            knowledge_score=data.knowledge_score or 0.0,
            attitude_score=data.attitude_score or 0.0,
            skill_score=data.skill_score or 0.0,
        )
        db.add(profile)
        await db.flush()
        await db.refresh(profile)  # reload server-side defaults
        return self.to_response(profile)

    def to_response(self, instance: KASProfile) -> KASProfileResponse:
        return KASProfileResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            knowledge_score=instance.knowledge_score,
            attitude_score=instance.attitude_score,
            skill_score=instance.skill_score,
        )


# ======================== Module-level singletons ========================

memory_block_service = MemoryBlockService()
tag_service = TagService()
knowledge_domain_service = KnowledgeDomainService()
kas_profile_service = KASProfileService()

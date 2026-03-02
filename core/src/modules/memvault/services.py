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

from .models import (
    EMBEDDING_DIM,
    BlockArchive,
    BlockEmbedding,
    KnowledgeDomain,
    MemoryBlock,
    ProfileScore,
    Tag,
)
from .schemas import (
    BLOCK_TYPE_ALIASES,
    BLOCK_TYPES,
    KnowledgeDomainCreate,
    KnowledgeDomainResponse,
    KnowledgeDomainUpdate,
    MemoryBlockCreate,
    MemoryBlockResponse,
    MemoryBlockUpdate,
    ProfileScoreResponse,
    ProfileScoreUpdate,
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
        # Normalize pipeline aliases (insight→knowledge, etc.) to canonical KAS types
        d["block_type"] = BLOCK_TYPE_ALIASES.get(d["block_type"], d["block_type"])
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
        """Vector similarity search using pgvector cosine distance.

        Tries block_embeddings sub-table first (Phase 2 path);
        falls back to inline blocks.embedding for backward compatibility.
        """
        if len(query_embedding) != EMBEDDING_DIM:
            raise BadRequestError(
                f"Embedding must be {EMBEDDING_DIM}d, got {len(query_embedding)}d",
                code="memvault.invalid_embedding_dim",
            )

        # Phase 2 path: search via embedding sub-table
        results = await self._search_via_subtable(
            db, space_id, query_embedding, top_k, threshold, tags, block_type
        )
        if results:
            return results

        # Fallback: inline embedding column (pre-Phase 2 or partial migration)
        return await self._search_via_inline(
            db, space_id, query_embedding, top_k, threshold, tags, block_type
        )

    async def _search_via_subtable(
        self,
        db: AsyncSession,
        space_id: str,
        query_embedding: list[float],
        top_k: int,
        threshold: float,
        tags: list[str] | None,
        block_type: str | None,
    ) -> list[SemanticSearchResult]:
        """Search using the block_embeddings sub-table (Phase 2)."""
        distance = BlockEmbedding.embedding.cosine_distance(query_embedding)
        similarity = (1 - distance).label("similarity")

        q = (
            select(MemoryBlock, similarity)
            .join(BlockEmbedding, BlockEmbedding.block_id == MemoryBlock.id)
            .where(
                MemoryBlock.space_id == space_id,
                distance < (1 - threshold),
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

    async def _search_via_inline(
        self,
        db: AsyncSession,
        space_id: str,
        query_embedding: list[float],
        top_k: int,
        threshold: float,
        tags: list[str] | None,
        block_type: str | None,
    ) -> list[SemanticSearchResult]:
        """Search using the inline embedding column (pre-Phase 2 fallback)."""
        distance = MemoryBlock.embedding.cosine_distance(query_embedding)
        similarity = (1 - distance).label("similarity")

        q = (
            select(MemoryBlock, similarity)
            .where(
                MemoryBlock.space_id == space_id,
                MemoryBlock.embedding.isnot(None),
                distance < (1 - threshold),
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

    async def text_search(
        self,
        db: AsyncSession,
        space_id: str,
        query: str,
        top_k: int = 10,
        include_archived: bool = False,
    ) -> list[SemanticSearchResult]:
        """Fallback text search using ILIKE when embeddings are unavailable.

        When include_archived=True, also searches blocks_archive table.
        """
        pattern = f"%{query}%"
        q = (
            select(MemoryBlock)
            .where(
                MemoryBlock.space_id == space_id,
                MemoryBlock.content.ilike(pattern),
            )
            .order_by(MemoryBlock.updated_at.desc())
            .limit(top_k)
        )
        rows = (await db.execute(q)).scalars().all()
        results = [
            SemanticSearchResult(block=self.to_response(r), score=0.5)
            for r in rows
        ]

        # Phase 3: search archived blocks if requested and under limit
        if include_archived and len(results) < top_k:
            remaining = top_k - len(results)
            archive_q = (
                select(BlockArchive)
                .where(
                    BlockArchive.space_id == space_id,
                    BlockArchive.content.ilike(pattern),
                )
                .order_by(BlockArchive.created_at.desc())
                .limit(remaining)
            )
            archive_rows = (await db.execute(archive_q)).scalars().all()
            results.extend([
                SemanticSearchResult(
                    block=MemoryBlockResponse(
                        id=r.id,
                        space_id=r.space_id,
                        created_by=r.created_by,
                        created_at=r.created_at,
                        updated_at=r.updated_at,
                        content=r.content,
                        block_type=r.block_type,
                        tags=r.tags or [],
                        source_session=r.source_session,
                        confidence=r.confidence or 0.0,
                    ),
                    score=0.3,  # lower score to indicate archived result
                )
                for r in archive_rows
            ])

        return results

    async def update_embedding(
        self, db: AsyncSession, block_id: str, embedding: list[float]
    ) -> None:
        """Set or update the embedding vector for a block.

        Writes to both inline column (backward compat) and sub-table (Phase 2).
        """
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

        # Upsert into sub-table
        existing = await db.get(BlockEmbedding, block_id)
        if existing:
            existing.embedding = embedding
        else:
            db.add(BlockEmbedding(block_id=block_id, embedding=embedding))


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


# ======================== ProfileScore Service ========================


class ProfileScoreService:
    """Single profile score per space — K/A/S aggregate scores."""

    async def get_by_space(
        self, db: AsyncSession, space_id: str
    ) -> ProfileScoreResponse | None:
        q = select(ProfileScore).where(ProfileScore.space_id == space_id)
        instance = (await db.execute(q)).scalar_one_or_none()
        if not instance:
            return None
        return ProfileScoreResponse(
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
        data: ProfileScoreUpdate,
        user_id: str | None = None,
    ) -> ProfileScoreResponse:
        q = select(ProfileScore).where(ProfileScore.space_id == space_id)
        existing = (await db.execute(q)).scalar_one_or_none()
        if existing:
            updates = data.model_dump(exclude_unset=True)
            for key, value in updates.items():
                setattr(existing, key, value)
            await db.flush()
            await db.refresh(existing)  # reload server-side onupdate fields
            return self.to_response(existing)
        # Create new
        profile = ProfileScore(
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

    def to_response(self, instance: ProfileScore) -> ProfileScoreResponse:
        return ProfileScoreResponse(
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
profile_score_service = ProfileScoreService()

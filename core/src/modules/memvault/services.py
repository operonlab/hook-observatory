"""Memvault services — CRUD + semantic search.

This is the PUBLIC API of the memvault module.
Other modules import from here, never from models.py.
"""

import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.events.types import MemvaultEvents
from src.shared.errors import BadRequestError, NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService
from src.shared.tier_config import get_threshold

from .models import (
    EMBEDDING_DIM,
    BlockArchive,
    BlockEmbedding,
    KnowledgeDomain,
    MemoryBlock,
    ProfileScore,
    Tag,
)
from .noise_filter import QUARANTINE_TAG, check_noise, filter_results
from .reranker import rerank_results
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
    SearchMetadata,
    SemanticSearchResult,
    TagResponse,
)
from .scopes import parse_scopes, scopes_to_filters
from .scoring_pipeline import ScoringConfig, ScoringPipeline

# --- CJK detection helper ---

_CJK_RANGES = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\u3040-\u309f"
    r"\u30a0-\u30ff\uff00-\uffef\uac00-\ud7af]"
)

# --- Greeting patterns (shared with noise_filter for should_search) ---

_GREETING_ONLY = re.compile(
    r"^(hi|hello|hey|howdy|yo|sup|greetings|good\s*(morning|afternoon|evening|night)"
    r"|你好|嗨|哈囉|早安|午安|晚安|哈嘍|嘿)[\s!.,、。\uff01]*$",
    re.IGNORECASE,
)


def _is_cjk_dominant(text: str) -> bool:
    """Check if text is predominantly CJK characters."""
    if not text:
        return False
    cjk_count = len(_CJK_RANGES.findall(text))
    return cjk_count / len(text) > 0.3


def _is_cjk(text: str) -> bool:
    """Check if text contains any CJK characters."""
    return bool(_CJK_RANGES.search(text))


def should_search(query: str) -> tuple[bool, str]:
    """Determine if a query warrants memory retrieval."""
    stripped = query.strip()
    # Too short
    if _is_cjk_dominant(stripped) and len(stripped) < 3:
        return False, "cjk_too_short"
    if not _is_cjk_dominant(stripped) and len(stripped) < 10:
        return False, "too_short"
    # Pure greeting
    if _GREETING_ONLY.match(stripped):
        return False, "greeting"
    # Memory keywords force search
    memory_kw = [
        "記得",
        "之前",
        "上次",
        "remember",
        "previously",
        "earlier",
        "last time",
        "recall",
    ]
    if any(kw in stripped.lower() for kw in memory_kw):
        return True, "memory_keyword"
    return True, "default"


# ======================== MemoryBlock Service ========================


class MemoryBlockService(
    BaseCRUDService[MemoryBlock, MemoryBlockCreate, MemoryBlockUpdate, MemoryBlockResponse]
):
    model = MemoryBlock
    audit_module = "memvault"
    audit_entity_type = "blocks"

    def before_create(self, data: MemoryBlockCreate, **kwargs: Any) -> dict:
        d = data.model_dump()
        # Normalize pipeline aliases (insight→knowledge, etc.) to canonical KAS types
        d["block_type"] = BLOCK_TYPE_ALIASES.get(d["block_type"], d["block_type"])
        if d["block_type"] not in BLOCK_TYPES:
            raise BadRequestError(
                f"Invalid block_type: {d['block_type']}",
                code="memvault.invalid_block_type",
            )
        # Phase A1: Noise quarantine — tag noisy content instead of rejecting
        verdict = check_noise(d.get("content", ""))
        if verdict.is_noise:
            tags = d.get("tags") or []
            if QUARANTINE_TAG not in tags:
                tags = [*tags, QUARANTINE_TAG]
            d["tags"] = tags
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
            MemoryBlock.deleted_at == None,  # noqa: E711
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
            MemoryBlock.deleted_at == None,  # noqa: E711
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
        threshold: float = 0.3,
        tags: list[str] | None = None,
        block_type: str | None = None,
        include_warm: bool = True,
        query: str | None = None,
        scoring_config: ScoringConfig | None = None,
        scope: str | None = None,
    ) -> tuple[list[SemanticSearchResult], SearchMetadata]:
        """Vector similarity search with RRF hybrid retrieval + scoring pipeline.

        Tries block_embeddings sub-table first (Phase 2 path);
        falls back to inline blocks.embedding for backward compat.

        When include_warm=True (default), augments results with
        warm-tier text search (score x 0.7) for blocks between
        hot_days and warm_days age that no longer have HNSW indexes.

        Returns (results, metadata) tuple.
        """
        if len(query_embedding) != EMBEDDING_DIM:
            raise BadRequestError(
                f"Embedding must be {EMBEDDING_DIM}d, got {len(query_embedding)}d",
                code="memvault.invalid_embedding_dim",
            )

        meta = SearchMetadata(vector_used=True, scope=scope)

        # Defense ⑦: Parse scope and build extra filters
        extra_filters = scopes_to_filters(parse_scopes(scope)) if scope else []

        # Phase B1: Run vector search + keyword search sequentially
        # (async SQLAlchemy session does not support concurrent queries)
        vector_results = await self._vector_search_combined(
            db,
            space_id,
            query_embedding,
            top_k,
            threshold,
            tags,
            block_type,
            extra_filters=extra_filters,
        )

        if query:
            keyword_results = await self._keyword_search(
                db,
                space_id,
                query,
                top_k,
                tags,
                block_type,
                extra_filters=extra_filters,
            )
            meta.keyword_used = True
            # RRF Fusion
            results = await self._rrf_fuse(vector_results, keyword_results)
        else:
            results = await vector_coro

        # Warm tier: text-based augmentation for older blocks
        if include_warm and len(results) < top_k:
            warm_results = await self._warm_tier_search(
                db,
                space_id,
                top_k - len(results),
                tags,
                block_type,
                extra_filters=extra_filters,
            )
            results.extend(warm_results)

        # Phase A1 + A2: Noise filter on results + Scoring Pipeline
        results, _ = filter_results(results)

        # Convert to scoring pipeline format
        pipeline = ScoringPipeline(scoring_config)
        scored_dicts = [
            {
                "block": r.block,
                "score": r.score,
                "content": r.block.content,
                "created_at": r.block.created_at,
                "confidence": r.block.confidence,
                "embedding": None,
            }
            for r in results
        ]

        scored_dicts, scoring_meta = pipeline.apply(scored_dicts, query_embedding)

        # Phase C2: Optional cross-encoder reranking
        if query:
            scored_dicts, reranked = await rerank_results(query, scored_dicts)
            if reranked:
                meta.reranker_used = True

        # Update metadata
        meta.scoring_applied = True
        meta.stages_applied = scoring_meta.stages_applied
        meta.stages_skipped = scoring_meta.stages_skipped
        meta.noise_filtered = scoring_meta.noise_filtered
        meta.input_count = scoring_meta.input_count
        meta.output_count = scoring_meta.output_count

        # Convert back to SemanticSearchResult
        final_results = [
            SemanticSearchResult(
                block=d["block"],
                score=round(d["score"], 4),
            )
            for d in scored_dicts[:top_k]
        ]

        return final_results, meta

    async def _vector_search_combined(
        self,
        db: AsyncSession,
        space_id: str,
        query_embedding: list[float],
        top_k: int,
        threshold: float,
        tags: list[str] | None,
        block_type: str | None,
        extra_filters: list | None = None,
    ) -> list[SemanticSearchResult]:
        """Run vector search: subtable first, fallback to inline."""
        results = await self._search_via_subtable(
            db,
            space_id,
            query_embedding,
            top_k,
            threshold,
            tags,
            block_type,
            extra_filters=extra_filters,
        )
        if not results:
            results = await self._search_via_inline(
                db,
                space_id,
                query_embedding,
                top_k,
                threshold,
                tags,
                block_type,
                extra_filters=extra_filters,
            )
        return results

    async def _keyword_search(
        self,
        db: AsyncSession,
        space_id: str,
        query: str,
        top_k: int,
        tags: list[str] | None = None,
        block_type: str | None = None,
        extra_filters: list | None = None,
    ) -> list[SemanticSearchResult]:
        """PostgreSQL keyword search.

        Uses tsvector for English text; falls back to ILIKE for CJK.
        """
        if _is_cjk(query):
            # CJK: use ILIKE
            pattern = f"%{query}%"
            q = (
                select(MemoryBlock)
                .where(
                    MemoryBlock.space_id == space_id,
                    MemoryBlock.content.ilike(pattern),
                    MemoryBlock.deleted_at == None,  # noqa: E711
                )
                .order_by(MemoryBlock.updated_at.desc())
                .limit(top_k)
            )
        else:
            # English: use tsvector + ts_rank_cd
            ts_query = func.plainto_tsquery("english", query)
            ts_vector = func.to_tsvector("english", MemoryBlock.content)
            rank = func.ts_rank_cd(ts_vector, ts_query).label("rank")
            q = (
                select(MemoryBlock, rank)
                .where(
                    MemoryBlock.space_id == space_id,
                    ts_vector.op("@@")(ts_query),
                    MemoryBlock.deleted_at == None,  # noqa: E711
                )
                .order_by(rank.desc())
                .limit(top_k)
            )

        if tags:
            q = q.where(MemoryBlock.tags.contains(tags))
        if block_type:
            q = q.where(MemoryBlock.block_type == block_type)
        for f in extra_filters or []:
            q = q.where(f)

        rows = (await db.execute(q)).all()

        results = []
        for row in rows:
            if _is_cjk(query):
                block = row
                score = 0.5
            else:
                block = row.MemoryBlock
                score = float(row.rank) if row.rank else 0.3
            results.append(
                SemanticSearchResult(
                    block=self.to_response(block),
                    score=round(score, 4),
                )
            )
        return results

    async def _rrf_fuse(
        self,
        vector_results: list[SemanticSearchResult],
        keyword_results: list[SemanticSearchResult],
        k: int = 60,
        keyword_boost: float = 0.15,
    ) -> list[SemanticSearchResult]:
        """Reciprocal Rank Fusion: combine vector and keyword results."""
        scores: dict[str, float] = {}
        best_result: dict[str, SemanticSearchResult] = {}

        # Score from vector results
        for rank, r in enumerate(vector_results):
            block_id = r.block.id
            scores[block_id] = scores.get(block_id, 0) + 1.0 / (k + rank)
            if block_id not in best_result or r.score > best_result[block_id].score:
                best_result[block_id] = r

        # Score from keyword results with boost
        keyword_ids = set()
        for rank, r in enumerate(keyword_results):
            block_id = r.block.id
            keyword_ids.add(block_id)
            scores[block_id] = scores.get(block_id, 0) + (1.0 / (k + rank) * (1 + keyword_boost))
            if block_id not in best_result or r.score > best_result[block_id].score:
                best_result[block_id] = r

        # Sort by fused score, but keep original similarity as the result score
        # (RRF scores are tiny ~0.01 and unsuitable for downstream min_score filtering)
        sorted_ids = sorted(scores, key=lambda bid: scores[bid], reverse=True)
        return [
            SemanticSearchResult(
                block=best_result[bid].block,
                score=round(best_result[bid].score, 4),
            )
            for bid in sorted_ids
        ]

    async def _search_via_subtable(
        self,
        db: AsyncSession,
        space_id: str,
        query_embedding: list[float],
        top_k: int,
        threshold: float,
        tags: list[str] | None,
        block_type: str | None,
        extra_filters: list | None = None,
    ) -> list[SemanticSearchResult]:
        """Search using the block_embeddings sub-table (Phase 2)."""
        distance = BlockEmbedding.embedding.cosine_distance(query_embedding)
        similarity = (1 - distance).label("similarity")

        q = (
            select(MemoryBlock, similarity)
            .join(BlockEmbedding, BlockEmbedding.block_id == MemoryBlock.id)
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
        for f in extra_filters or []:
            q = q.where(f)

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
        extra_filters: list | None = None,
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
        for f in extra_filters or []:
            q = q.where(f)

        rows = (await db.execute(q)).all()
        return [
            SemanticSearchResult(
                block=self.to_response(row.MemoryBlock),
                score=round(float(row.similarity), 4),
            )
            for row in rows
        ]

    async def _warm_tier_search(
        self,
        db: AsyncSession,
        space_id: str,
        remaining: int,
        tags: list[str] | None,
        block_type: str | None,
        extra_filters: list | None = None,
    ) -> list[SemanticSearchResult]:
        """Search warm-tier blocks (no HNSW, still in main table).

        Warm tier: hot_days < age <= warm_days.
        Uses ILIKE on content; score = best_hnsw_score * 0.7
        (capped at 0.5 * 0.7 = 0.35 for text matches).
        """
        tier = get_threshold("memvault")
        now = datetime.now(UTC)
        hot_cutoff = now - timedelta(days=tier.hot_days)
        warm_cutoff = now - timedelta(days=tier.warm_days)

        q = (
            select(MemoryBlock)
            .where(
                MemoryBlock.space_id == space_id,
                MemoryBlock.created_at < hot_cutoff,
                MemoryBlock.created_at >= warm_cutoff,
            )
            .order_by(MemoryBlock.updated_at.desc())
            .limit(remaining)
        )
        if tags:
            q = q.where(MemoryBlock.tags.contains(tags))
        if block_type:
            q = q.where(MemoryBlock.block_type == block_type)
        for f in extra_filters or []:
            q = q.where(f)

        rows = (await db.execute(q)).scalars().all()
        return [
            SemanticSearchResult(
                block=self.to_response(r),
                score=0.35,  # warm tier: 0.5 * 0.7
            )
            for r in rows
        ]

    async def text_search(
        self,
        db: AsyncSession,
        space_id: str,
        query: str,
        top_k: int = 10,
        include_archived: bool = False,
        include_warm: bool = True,
        scope: str | None = None,
    ) -> list[SemanticSearchResult]:
        """Fallback text search using ILIKE.

        Tier-aware search:
          Hot  (age <= hot_days): score 0.5
          Warm (hot_days < age <= warm_days): score 0.35
          Cold (archive table, include_archived): score 0.3
        """
        pattern = f"%{query}%"
        tier = get_threshold("memvault")
        now = datetime.now(UTC)
        hot_cutoff = now - timedelta(days=tier.hot_days)
        warm_cutoff = now - timedelta(days=tier.warm_days)

        # Defense ⑦: Parse scope filters
        extra_filters = scopes_to_filters(parse_scopes(scope)) if scope else []

        # --- Hot tier: recent blocks (full index coverage) ---
        hot_q = (
            select(MemoryBlock)
            .where(
                MemoryBlock.space_id == space_id,
                MemoryBlock.content.ilike(pattern),
                MemoryBlock.created_at >= hot_cutoff,
            )
            .order_by(MemoryBlock.updated_at.desc())
            .limit(top_k)
        )
        for f in extra_filters:
            hot_q = hot_q.where(f)
        hot_rows = (await db.execute(hot_q)).scalars().all()
        results: list[SemanticSearchResult] = [
            SemanticSearchResult(
                block=self.to_response(r),
                score=0.5,
            )
            for r in hot_rows
        ]

        # --- Warm tier: older blocks still in main table ---
        if include_warm and len(results) < top_k:
            remaining = top_k - len(results)
            warm_q = (
                select(MemoryBlock)
                .where(
                    MemoryBlock.space_id == space_id,
                    MemoryBlock.content.ilike(pattern),
                    MemoryBlock.created_at < hot_cutoff,
                    MemoryBlock.created_at >= warm_cutoff,
                )
                .order_by(MemoryBlock.updated_at.desc())
                .limit(remaining)
            )
            for f in extra_filters:
                warm_q = warm_q.where(f)
            warm_rows = (await db.execute(warm_q)).scalars().all()
            results.extend(
                [
                    SemanticSearchResult(
                        block=self.to_response(r),
                        score=0.35,  # warm: 0.5 * 0.7
                    )
                    for r in warm_rows
                ]
            )

        # --- Cold tier: archive table ---
        if include_archived and len(results) < top_k:
            remaining = top_k - len(results)
            archive_q = (
                select(BlockArchive)
                .where(
                    BlockArchive.space_id == space_id,
                    BlockArchive.content.ilike(pattern),
                    ~BlockArchive.content.like("s3://%"),
                )
                .order_by(BlockArchive.created_at.desc())
                .limit(remaining)
            )
            archive_rows = (await db.execute(archive_q)).scalars().all()
            results.extend(
                [
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
                        score=0.3,  # cold: archived result
                    )
                    for r in archive_rows
                ]
            )

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
            update(MemoryBlock).where(MemoryBlock.id == block_id).values(embedding=embedding)
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

    async def list_tags(self, db: AsyncSession, space_id: str) -> list[TagResponse]:
        """List all tags for a space, ordered by usage count."""
        q = select(Tag).where(Tag.space_id == space_id).order_by(Tag.usage_count.desc())
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
    audit_module = "memvault"
    audit_entity_type = "knowledge_domains"

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

    async def get_by_space(self, db: AsyncSession, space_id: str) -> ProfileScoreResponse | None:
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

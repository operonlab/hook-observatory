"""Memvault KG Services — Triple, Community, CommunitySummary, Attitude, Skill, CascadeRecall.

This is the public KG API of the memvault module.
Other modules import from here, never from kg_models.py.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.events.types import MemvaultEvents
from src.shared.errors import ConflictError, NotFoundError
from src.shared.services import BaseCRUDService

from .embedding import get_embedding
from .entity_resolution import entity_resolution_service, normalize_entity_text
from .kg_config import normalize_predicate
from .kg_models import (
    AttitudeFact,
    Community,
    CommunitySummary,
    CommunityTriple,
    SkillInvocation,
    SkillProfile,
    Triple,
)
from .kg_schemas import (
    AttitudeEvolveRequest,
    AttitudeEvolveResult,
    AttitudeFactCreate,
    AttitudeFactResponse,
    CascadeRecallResult,
    CommunityDetail,
    CommunityResponse,
    CommunitySummaryResponse,
    GraphEdge,
    GraphNode,
    GraphTraversalResult,
    SkillInvocationCreate,
    SkillInvocationResponse,
    SkillProficiencyResponse,
    SkillProfileResponse,
    SkillProfileUpsert,
    TripleBatchCreate,
    TripleCreate,
    TripleResponse,
)

logger = logging.getLogger(__name__)


# ======================== TripleUpdate (lightweight) ========================


from pydantic import BaseModel


class TripleUpdate(BaseModel):
    """Partial update schema for Triple — triples are generally immutable."""

    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    topic: str | None = None
    timestamp: datetime | None = None


# ======================== TripleService ========================


class TripleService(BaseCRUDService[Triple, TripleCreate, TripleUpdate, TripleResponse]):
    """CRUD + batch ingest + semantic search for L0 Triple facts."""

    model = Triple
    audit_module = "memvault"
    event_types = {"created": MemvaultEvents.TRIPLE_INGESTED}
    event_id_alias = "triple_id"
    event_fields = ("subject", "predicate", "source_session")

    def before_create(self, data: TripleCreate, **kwargs: Any) -> dict:
        """Normalize predicate and entity text before inserting."""
        d = data.model_dump()
        d["predicate"] = normalize_predicate(d["predicate"])
        d["subject"] = normalize_entity_text(d["subject"])
        d["object"] = normalize_entity_text(d["object"])
        return d

    def to_response(self, instance: Triple) -> TripleResponse:
        """Map ORM instance to TripleResponse (embedding excluded)."""
        return TripleResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            subject=instance.subject,
            predicate=instance.predicate,
            object=instance.object,
            source_session=instance.source_session,
            timestamp=instance.timestamp,
            topic=instance.topic,
            display_zh=instance.display_zh,
            valid_at=instance.valid_at,
            invalid_at=instance.invalid_at,
            invalidated_by=instance.invalidated_by,
            invalidation_reason=instance.invalidation_reason,
            canonical_subject_id=instance.canonical_subject_id,
            canonical_object_id=instance.canonical_object_id,
        )

    async def batch_ingest(
        self,
        db: AsyncSession,
        space_id: str,
        batch: TripleBatchCreate,
    ) -> list[Triple]:
        """Batch ingest triples from a session extraction pipeline.

        Normalizes predicates, generates embeddings (best-effort), and skips
        duplicates via IntegrityError handling.
        """
        created: list[Triple] = []

        invalidated_count = 0
        for item in batch.triples:
            predicate = normalize_predicate(item.predicate)
            subject = normalize_entity_text(item.subject)
            object_text = normalize_entity_text(item.object)
            topic = batch.topic or item.topic
            timestamp = batch.timestamp or item.timestamp

            triple = Triple(
                space_id=space_id,
                source_session=batch.session_id,
                subject=subject,
                predicate=predicate,
                object=object_text,
                topic=topic,
                timestamp=timestamp,
            )
            # embedding column removed (Qdrant migration) — indexed via Qdrant after flush
            db.add(triple)
            try:
                await db.flush()
                # Entity resolution (best-effort)
                await entity_resolution_service.resolve_and_link_triple(db, space_id, triple)
                # Detect and invalidate contradictions
                contradictions = await self.detect_contradictions(db, space_id, triple)
                for old_triple in contradictions:
                    old_triple.invalid_at = datetime.now(UTC)
                    old_triple.invalidated_by = triple.id
                    old_triple.invalidation_reason = "contradiction"
                    invalidated_count += 1
                    logger.info(
                        "Auto-invalidated triple %s (replaced by %s)",
                        old_triple.id,
                        triple.id,
                    )
                if contradictions:
                    await db.flush()
                created.append(triple)
            except IntegrityError:
                await db.rollback()
                logger.debug(
                    "Skipping duplicate triple: %s %s %s (session=%s)",
                    subject,
                    predicate,
                    object_text,
                    batch.session_id,
                )

        if created:
            event_bus.publish_fire_and_forget(
                Event(
                    type=MemvaultEvents.TRIPLE_BATCH_INGESTED,
                    data={
                        "space_id": space_id,
                        "session_id": batch.session_id,
                        "count": len(created),
                    },
                    source="memvault",
                )
            )
            # Post-ingest auto-merge (best-effort, >= 0.95 only)
            try:
                merges = await entity_resolution_service.auto_merge(
                    db, space_id, threshold=0.95, max_merges=10
                )
                if merges:
                    logger.info(
                        "Post-ingest auto-merged %d entity pairs (space=%s)",
                        len(merges),
                        space_id,
                    )
            except Exception:
                logger.warning("Post-ingest auto-merge failed", exc_info=True)

        return created

    async def search_by_predicate(
        self,
        db: AsyncSession,
        space_id: str,
        predicate: str,
        subject: str | None = None,
        object: str | None = None,
        limit: int = 50,
        include_invalid: bool = False,
    ) -> list[TripleResponse]:
        """Query triples by predicate, optionally filtered by subject or object."""
        canonical = normalize_predicate(predicate)
        q = (
            select(Triple)
            .where(
                Triple.space_id == space_id,
                Triple.predicate == canonical,
            )
            .limit(limit)
        )
        if not include_invalid:
            q = q.where(Triple.invalid_at.is_(None))
        if subject is not None:
            q = q.where(Triple.subject.ilike(f"%{subject}%"))
        if object is not None:
            q = q.where(Triple.object.ilike(f"%{object}%"))

        rows = (await db.execute(q)).scalars().all()
        return [self.to_response(r) for r in rows]

    async def semantic_search(
        self,
        db: AsyncSession,
        space_id: str,
        query_embedding: list[float],
        top_k: int = 10,
        threshold: float = 0.5,
    ) -> list[TripleResponse]:
        """Vector similarity search on triples — Qdrant primary, pgvector legacy fallback."""
        from src.shared.qdrant_client import is_available as qdrant_available
        from src.shared.qdrant_search import vector_search
        from src.shared.search_types import SearchConfig

        if await qdrant_available():
            config = SearchConfig(
                top_k=top_k,
                score_threshold=threshold,
                service_ids=["memvault-triple"],
            )
            results = await vector_search(query_embedding, space_id, config)
            if results:
                triple_ids = [r.entity_id for r in results]
                q = select(Triple).where(
                    Triple.id.in_(triple_ids),
                    Triple.invalid_at.is_(None),
                )
                rows = (await db.execute(q)).scalars().all()
                id_order = {eid: i for i, eid in enumerate(triple_ids)}
                rows = sorted(rows, key=lambda r: id_order.get(str(r.id), 999))
                return [self.to_response(r) for r in rows]
            return []

        return []

    async def delete_by_id(self, db: AsyncSession, id: str) -> None:
        result = await db.execute(select(self.model).where(self.model.id == id))
        instance = result.scalar_one_or_none()
        if not instance:
            raise NotFoundError("Triple not found", code="memvault.triple_not_found")
        await db.delete(instance)

    async def update_by_id(self, db: AsyncSession, id: str, data: TripleCreate) -> Triple:
        result = await db.execute(select(self.model).where(self.model.id == id))
        instance = result.scalar_one_or_none()
        if not instance:
            raise NotFoundError("Triple not found", code="memvault.triple_not_found")
        d = data.model_dump(exclude_unset=True)
        if "predicate" in d:
            d["predicate"] = normalize_predicate(d["predicate"])
        for key, val in d.items():
            setattr(instance, key, val)
        return instance

    async def invalidate(
        self,
        db: AsyncSession,
        triple_id: str,
        reason: str = "manual",
        replacement_id: str | None = None,
    ) -> Triple:
        """Mark a triple as invalidated (edge invalidation)."""
        result = await db.execute(select(Triple).where(Triple.id == triple_id))
        instance = result.scalar_one_or_none()
        if not instance:
            raise NotFoundError("Triple not found", code="memvault.triple_not_found")
        if instance.invalid_at is not None:
            raise ConflictError(
                "Triple already invalidated", code="memvault.triple_already_invalid"
            )

        instance.invalid_at = datetime.now(UTC)
        instance.invalidation_reason = reason
        if replacement_id:
            instance.invalidated_by = replacement_id
        await db.flush()

        event_bus.publish_fire_and_forget(
            Event(
                type=MemvaultEvents.TRIPLE_INVALIDATED,
                data={
                    "triple_id": triple_id,
                    "reason": reason,
                    "replacement_id": replacement_id,
                },
                source="memvault",
            )
        )
        return instance

    async def detect_contradictions(
        self,
        db: AsyncSession,
        space_id: str,
        new_triple: Triple,
        similarity_threshold: float = 0.85,
    ) -> list[Triple]:
        """Find valid triples that contradict the new triple.

        Same subject + same predicate + high embedding similarity + different object.
        """
        # embedding column removed from Triple (Qdrant migration) — use Qdrant vector search
        from src.shared.qdrant_client import is_available as qdrant_available
        from src.shared.qdrant_search import vector_search
        from src.shared.search_types import SearchConfig

        if not await qdrant_available():
            return []

        # Get embedding for contradiction detection via text
        embedding_text = f"{new_triple.subject} {new_triple.predicate} {new_triple.object}"
        embedding = await get_embedding(embedding_text)
        if embedding is None:
            return []

        config = SearchConfig(
            top_k=10,
            score_threshold=similarity_threshold,
            service_ids=["memvault-triple"],
        )
        results = await vector_search(embedding, space_id, config)
        if not results:
            return []
        triple_ids = [r.entity_id for r in results]
        q = select(Triple).where(
            Triple.id.in_(triple_ids),
            Triple.id != new_triple.id,
            Triple.invalid_at.is_(None),
            Triple.subject == new_triple.subject,
            Triple.predicate == new_triple.predicate,
        )
        candidates = (await db.execute(q)).scalars().all()
        return [
            c for c in candidates if c.object.strip().lower() != new_triple.object.strip().lower()
        ]


# ======================== GraphTraversalService ========================


class GraphTraversalService:
    """SQL-based multi-hop graph traversal using PostgreSQL recursive CTE."""

    MAX_DEPTH_CAP = 4
    MAX_RESULTS_CAP = 500
    QUERY_TIMEOUT_MS = 5000

    async def traverse(
        self,
        db: AsyncSession,
        space_id: str,
        entity: str,
        max_depth: int = 2,
        direction: str = "both",
        predicate_filter: list[str] | None = None,
        max_results: int = 200,
    ) -> GraphTraversalResult:
        """Multi-hop graph traversal from a seed entity."""
        from sqlalchemy import text as sa_text

        max_depth = min(max_depth, self.MAX_DEPTH_CAP)
        max_results = min(max_results, self.MAX_RESULTS_CAP)

        # Build direction-specific CTE
        predicates_clause = ""
        params: dict[str, Any] = {
            "entity": entity,
            "space_id": space_id,
            "max_depth": max_depth,
            "max_results": max_results,
        }
        if predicate_filter:
            predicates_clause = "AND t.predicate = ANY(:predicates)"
            params["predicates"] = predicate_filter

        # All values are parameterized (:entity, :space_id, :predicates, :max_depth)
        # predicates_clause is only "AND t.predicate = ANY(:predicates)" — safe
        if direction == "outgoing":
            seed = """
                SELECT id, subject, predicate, object, 1 AS depth,
                       ARRAY[id]::varchar[] AS path
                FROM memvault.triples
                WHERE subject = :entity AND space_id = :space_id
                  AND deleted_at IS NULL AND invalid_at IS NULL
            """
            recurse = f"""
                SELECT t.id, t.subject, t.predicate, t.object, g.depth + 1, g.path || t.id
                FROM memvault.triples t JOIN graph g ON t.subject = g.object
                WHERE g.depth < :max_depth AND t.space_id = :space_id
                  AND t.deleted_at IS NULL AND t.invalid_at IS NULL
                  AND t.id != ALL(g.path) {predicates_clause}
            """  # noqa: S608
        elif direction == "incoming":
            seed = """
                SELECT id, subject, predicate, object, 1 AS depth,
                       ARRAY[id]::varchar[] AS path
                FROM memvault.triples
                WHERE object = :entity AND space_id = :space_id
                  AND deleted_at IS NULL AND invalid_at IS NULL
            """
            recurse = f"""
                SELECT t.id, t.subject, t.predicate, t.object, g.depth + 1, g.path || t.id
                FROM memvault.triples t JOIN graph g ON t.object = g.subject
                WHERE g.depth < :max_depth AND t.space_id = :space_id
                  AND t.deleted_at IS NULL AND t.invalid_at IS NULL
                  AND t.id != ALL(g.path) {predicates_clause}
            """  # noqa: S608
        else:  # both
            seed = """
                SELECT id, subject, predicate, object, 1 AS depth,
                       ARRAY[id]::varchar[] AS path
                FROM memvault.triples
                WHERE (subject = :entity OR object = :entity) AND space_id = :space_id
                  AND deleted_at IS NULL AND invalid_at IS NULL
            """
            recurse = f"""
                SELECT t.id, t.subject, t.predicate, t.object, g.depth + 1, g.path || t.id
                FROM memvault.triples t JOIN graph g
                  ON (t.subject = g.object OR t.object = g.subject)
                WHERE g.depth < :max_depth AND t.space_id = :space_id
                  AND t.deleted_at IS NULL AND t.invalid_at IS NULL
                  AND t.id != ALL(g.path) {predicates_clause}
            """  # noqa: S608

        # Set statement timeout separately (can't combine in prepared stmt)
        await db.execute(sa_text(f"SET LOCAL statement_timeout = '{self.QUERY_TIMEOUT_MS}ms'"))

        sql = (
            f"WITH RECURSIVE graph AS ({seed} UNION ALL {recurse})"  # noqa: S608
            " SELECT DISTINCT ON (id) id, subject, predicate, object, depth"
            " FROM graph ORDER BY id, depth LIMIT :max_results"
        )

        result = await db.execute(sa_text(sql), params)
        rows = result.fetchall()

        # Build nodes + edges
        node_map: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        for row in rows:
            edge = GraphEdge(
                id=row.id,
                source=row.subject,
                target=row.object,
                predicate=row.predicate,
                depth=row.depth,
            )
            edges.append(edge)

            for name in (row.subject, row.object):
                if name not in node_map:
                    node_map[name] = GraphNode(
                        id=name,
                        label=name,
                        depth=row.depth if name != entity else 0,
                        triple_count=0,
                    )
                node_map[name].triple_count += 1
                if row.depth < node_map[name].depth:
                    node_map[name].depth = row.depth

        # Ensure seed entity is in nodes even if no results
        if entity not in node_map:
            node_map[entity] = GraphNode(id=entity, label=entity, depth=0)

        return GraphTraversalResult(
            seed_entity=entity,
            direction=direction,
            max_depth=max_depth,
            nodes=sorted(node_map.values(), key=lambda n: (n.depth, n.id)),
            edges=edges,
            total_triples_traversed=len(edges),
            truncated=len(edges) >= max_results,
        )


# ======================== CommunityService ========================


class CommunityService:
    """Manage L1 Community records (standalone — no BaseCRUD)."""

    def to_response(self, instance: Community) -> CommunityResponse:
        """Map ORM Community to CommunityResponse."""
        return CommunityResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            name=instance.name,
            resolution_level=instance.resolution_level,
            size=instance.size,
            top_entities=instance.top_entities or [],
            top_predicates=instance.top_predicates or [],
            summary=instance.summary,
            description_zh=instance.description_zh,
            parent_community_id=instance.parent_community_id,
            modularity_score=instance.modularity_score,
            generation_batch=instance.generation_batch,
        )

    async def list_communities(
        self,
        db: AsyncSession,
        space_id: str,
        resolution_level: int | None = None,
    ) -> list[CommunityResponse]:
        """List all communities for a space, ordered by size descending.

        Optionally filtered by resolution_level (0=fine, 1=medium, 2=coarse).
        """
        q = select(Community).where(Community.space_id == space_id).order_by(Community.size.desc())
        if resolution_level is not None:
            q = q.where(Community.resolution_level == resolution_level)
        rows = (await db.execute(q)).scalars().all()
        return [self.to_response(r) for r in rows]

    async def get_community_detail(
        self, db: AsyncSession, community_id: str
    ) -> CommunityDetail | None:
        """Get a community with its member triples and children communities."""
        community = await db.get(Community, community_id)
        if not community:
            return None

        # Fetch member triples via community_triples join
        q = (
            select(Triple)
            .join(CommunityTriple, CommunityTriple.triple_id == Triple.id)
            .where(CommunityTriple.community_id == community_id)
        )
        triple_rows = (await db.execute(q)).scalars().all()
        triple_svc = triple_service  # use module-level singleton

        # Fetch children communities
        children_q = select(Community).where(
            Community.parent_community_id == community_id,
            Community.space_id == community.space_id,
        )
        children_rows = (await db.execute(children_q)).scalars().all()

        return CommunityDetail(
            id=community.id,
            space_id=community.space_id,
            created_by=community.created_by,
            created_at=community.created_at,
            updated_at=community.updated_at,
            name=community.name,
            resolution_level=community.resolution_level,
            size=community.size,
            top_entities=community.top_entities or [],
            top_predicates=community.top_predicates or [],
            summary=community.summary,
            parent_community_id=community.parent_community_id,
            modularity_score=community.modularity_score,
            generation_batch=community.generation_batch,
            triples=[triple_svc.to_response(t) for t in triple_rows],
            children=[self.to_response(c) for c in children_rows],
        )

    async def save_communities(
        self,
        db: AsyncSession,
        space_id: str,
        communities_data: list[dict],
    ) -> int:
        """Atomically replace all communities for a space with fresh Leiden results.

        Deletes existing community_triples then communities, inserts new ones.
        Returns count of communities saved.
        """
        existing_community_ids = (
            select(Community.id).where(Community.space_id == space_id).scalar_subquery()
        )
        # Delete in FK dependency order: summaries → triples → communities
        await db.execute(
            delete(CommunitySummary).where(
                CommunitySummary.community_id.in_(existing_community_ids)
            )
        )
        await db.execute(
            delete(CommunityTriple).where(CommunityTriple.community_id.in_(existing_community_ids))
        )
        await db.execute(delete(Community).where(Community.space_id == space_id))

        saved = 0
        for c in communities_data:
            community = Community(
                space_id=space_id,
                name=c.get("name", ""),
                resolution_level=c.get("resolution_level", 0),
                size=c.get("size", 0),
                entity_ids=c.get("entity_ids"),
                top_entities=c.get("top_entities"),
                top_predicates=c.get("top_predicates"),
                summary=c.get("summary"),
                parent_community_id=c.get("parent_community_id"),
                modularity_score=c.get("modularity_score"),
                generation_batch=c.get("generation_batch"),
            )
            db.add(community)
            await db.flush()

            for triple_id in c.get("triple_ids", []):
                ct = CommunityTriple(
                    space_id=space_id,
                    community_id=community.id,
                    triple_id=triple_id,
                )
                db.add(ct)

            saved += 1

        await db.flush()

        event_bus.publish_fire_and_forget(
            Event(
                type=MemvaultEvents.COMMUNITY_REGENERATED,
                data={"space_id": space_id, "count": saved},
                source="memvault",
            )
        )

        # Index communities to Qdrant for semantic search (best-effort)
        await _index_communities_to_qdrant(db, space_id)

        return saved


async def _index_communities_to_qdrant(db: AsyncSession, space_id: str) -> None:
    """Batch index L1 communities into Qdrant after save_communities()."""
    try:
        from src.shared.qdrant_search import (
            delete_by_service_and_space,
            index_documents_batch,
        )
        from src.shared.search_types import IndexDocument

        # Atomic: delete old → upsert new
        await delete_by_service_and_space("memvault-community", space_id)

        communities = (
            (await db.execute(select(Community).where(Community.space_id == space_id)))
            .scalars()
            .all()
        )

        if not communities:
            return

        docs = []
        for c in communities:
            top_entities = (c.top_entities or [])[:10]
            top_predicates = (c.top_predicates or [])[:5]
            content_parts = [c.name]
            if c.description_zh:
                content_parts.append(c.description_zh)
            if c.summary:
                content_parts.append(c.summary)
            if top_entities:
                content_parts.append(f"Entities: {', '.join(top_entities)}")
            if top_predicates:
                content_parts.append(f"Predicates: {', '.join(top_predicates)}")

            docs.append(
                IndexDocument(
                    service_id="memvault-community",
                    entity_id=str(c.id),
                    entity_type="community",
                    space_id=space_id,
                    content="\n".join(content_parts),
                    tags=top_entities[:5],
                    created_at=c.created_at,
                )
            )

        indexed = await index_documents_batch(docs)
        logger.info(
            "Indexed %d/%d communities to Qdrant for space=%s",
            indexed,
            len(docs),
            space_id,
        )
    except Exception as e:
        logger.warning("Failed to index communities to Qdrant (non-fatal): %s", e)


# ======================== CommunitySummaryService ========================


class CommunitySummaryService:
    """Manage L2 CommunitySummary records (standalone)."""

    def to_response(self, instance: CommunitySummary) -> CommunitySummaryResponse:
        """Map ORM CommunitySummary to CommunitySummaryResponse."""
        return CommunitySummaryResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            community_id=instance.community_id,
            summary=instance.summary,
            key_findings=instance.key_findings or [],
            representative_triples=instance.representative_triples or [],
            evidence_count=instance.evidence_count,
            tags=instance.tags or [],
            llm_model=instance.llm_model,
        )

    async def list_summaries(
        self,
        db: AsyncSession,
        space_id: str,
        resolution_level: int | None = None,
    ) -> list[CommunitySummaryResponse]:
        """List community summaries for a space.

        Optionally filtered by the resolution_level of the parent community.
        """
        if resolution_level is not None:
            q = (
                select(CommunitySummary)
                .join(Community, Community.id == CommunitySummary.community_id)
                .where(
                    CommunitySummary.space_id == space_id,
                    Community.resolution_level == resolution_level,
                )
            )
        else:
            q = select(CommunitySummary).where(CommunitySummary.space_id == space_id)

        rows = (await db.execute(q)).scalars().all()
        return [self.to_response(r) for r in rows]

    async def save_summaries(
        self,
        db: AsyncSession,
        space_id: str,
        summaries_data: list[dict],
    ) -> int:
        """Atomically replace all community summaries for a space.

        Deletes existing community_summaries, inserts new ones.
        Returns count saved.
        """
        await db.execute(delete(CommunitySummary).where(CommunitySummary.space_id == space_id))

        saved = 0
        for s in summaries_data:
            node = CommunitySummary(
                space_id=space_id,
                community_id=s["community_id"],
                summary=s["summary"],
                key_findings=s.get("key_findings"),
                representative_triples=s.get("representative_triples"),
                evidence_count=s.get("evidence_count"),
                tags=s.get("tags"),
                llm_model=s.get("llm_model"),
                generation_batch=s.get("generation_batch"),
            )
            db.add(node)
            saved += 1

        await db.flush()

        event_bus.publish_fire_and_forget(
            Event(
                type=MemvaultEvents.COMMUNITY_SUMMARY_REGENERATED,
                data={"space_id": space_id, "count": saved},
                source="memvault",
            )
        )

        # Index summaries to Qdrant for semantic search (best-effort)
        await _index_summaries_to_qdrant(db, space_id)

        return saved


async def _index_summaries_to_qdrant(db: AsyncSession, space_id: str) -> None:
    """Batch index L2 community summaries into Qdrant after save_summaries()."""
    try:
        from src.shared.qdrant_search import (
            delete_by_service_and_space,
            index_documents_batch,
        )
        from src.shared.search_types import IndexDocument

        await delete_by_service_and_space("memvault-summary", space_id)

        summaries = (
            (
                await db.execute(
                    select(CommunitySummary).where(CommunitySummary.space_id == space_id)
                )
            )
            .scalars()
            .all()
        )

        if not summaries:
            return

        docs = []
        for s in summaries:
            content_parts = [s.summary]
            if s.key_findings:
                content_parts.extend(s.key_findings)

            docs.append(
                IndexDocument(
                    service_id="memvault-summary",
                    entity_id=str(s.id),
                    entity_type="community_summary",
                    space_id=space_id,
                    content="\n".join(content_parts),
                    tags=s.tags or [],
                    created_at=s.created_at,
                )
            )

        indexed = await index_documents_batch(docs)
        logger.info("Indexed %d/%d summaries to Qdrant for space=%s", indexed, len(docs), space_id)
    except Exception as e:
        logger.warning("Failed to index summaries to Qdrant (non-fatal): %s", e)


# ======================== AttitudeService ========================


class AttitudeService:
    """Versioned attitude/belief fact management with Mem0-style evolution (standalone)."""

    def to_response(self, instance: AttitudeFact) -> AttitudeFactResponse:
        """Convert ORM AttitudeFact to AttitudeFactResponse."""
        return AttitudeFactResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            fact=instance.fact,
            category=instance.category,
            operation=instance.operation,
            confidence=instance.confidence,
            source_sessions=instance.source_sessions or [],
            superseded_by=instance.superseded_by,
            previous_version=instance.previous_version,
        )

    async def get_current(
        self,
        db: AsyncSession,
        space_id: str,
        category: str | None = None,
    ) -> list[AttitudeFactResponse]:
        """Get current (non-superseded) attitude facts for a space.

        Optionally filtered by category.
        """
        q = select(AttitudeFact).where(
            AttitudeFact.space_id == space_id,
            AttitudeFact.superseded_by.is_(None),
        )
        if category is not None:
            q = q.where(AttitudeFact.category == category)

        rows = (await db.execute(q)).scalars().all()
        return [self.to_response(r) for r in rows]

    async def create_fact(
        self,
        db: AsyncSession,
        space_id: str,
        data: AttitudeFactCreate,
    ) -> AttitudeFact:
        """Directly create an attitude fact with operation=ADD."""
        embedding = await get_embedding(data.fact)
        fact = AttitudeFact(
            space_id=space_id,
            fact=data.fact,
            category=data.category,
            operation="ADD",
            confidence=0.5,
            source_sessions=data.source_sessions or [],
            embedding=embedding,
        )
        db.add(fact)
        await db.flush()
        return fact

    async def evolve(
        self,
        db: AsyncSession,
        space_id: str,
        request: AttitudeEvolveRequest,
    ) -> AttitudeEvolveResult:
        """Mem0 pattern: determine ADD/UPDATE/NOOP for a new fact.

        Compares the incoming fact against current facts in the same category
        via cosine similarity and applies ADD/UPDATE/NOOP accordingly.
        """
        new_embedding = await get_embedding(request.fact)

        # Fetch current facts in the same category
        q = select(AttitudeFact).where(
            AttitudeFact.space_id == space_id,
            AttitudeFact.category == request.category,
            AttitudeFact.superseded_by.is_(None),
        )
        current_facts = (await db.execute(q)).scalars().all()

        best_fact: AttitudeFact | None = None
        best_similarity: float = 0.0

        if new_embedding and current_facts:
            from src.shared.qdrant_client import is_available as qdrant_available
            from src.shared.qdrant_search import vector_search
            from src.shared.search_types import SearchConfig

            if await qdrant_available():
                config = SearchConfig(
                    top_k=1,
                    score_threshold=0.0,
                    service_ids=["memvault-attitude"],
                )
                results = await vector_search(new_embedding, space_id, config)
                if results:
                    best_id = results[0].entity_id
                    best_similarity = results[0].score
                    for f in current_facts:
                        if str(f.id) == best_id:
                            best_fact = f
                            break
            else:
                # pgvector fallback removed — embedding column dropped.
                # best_fact / best_similarity remain None/0.0 → decision logic below treats as NEW.
                pass

        # Decision logic
        if best_fact and best_similarity > 0.9:
            # NOOP — bump confidence on existing fact
            best_fact.confidence = min(1.0, best_fact.confidence + 0.05)
            await db.flush()
            event_bus.publish_fire_and_forget(
                Event(
                    type=MemvaultEvents.ATTITUDE_EVOLVED,
                    data={
                        "space_id": space_id,
                        "operation": "NOOP",
                        "fact_id": best_fact.id,
                        "similarity": best_similarity,
                    },
                    source="memvault",
                )
            )
            return AttitudeEvolveResult(
                operation="NOOP",
                fact_id=best_fact.id,
                message=f"Duplicate detected (similarity={best_similarity:.2f}); bumped.",
                previous_id=None,
            )

        if best_fact and best_similarity > 0.8:
            # UPDATE — supersede old, create new
            old_id = best_fact.id
            best_fact.superseded_by = old_id  # mark as superseded (self-ref placeholder)

            new_fact = AttitudeFact(
                space_id=space_id,
                fact=request.fact,
                category=request.category,
                operation="UPDATE",
                confidence=max(best_fact.confidence, 0.5),
                source_sessions=([request.source_session] if request.source_session else []),
                previous_version=old_id,
                embedding=new_embedding,
            )
            db.add(new_fact)
            await db.flush()
            # Now set superseded_by on old fact to the new fact's id
            best_fact.superseded_by = new_fact.id
            await db.flush()

            event_bus.publish_fire_and_forget(
                Event(
                    type=MemvaultEvents.ATTITUDE_EVOLVED,
                    data={
                        "space_id": space_id,
                        "operation": "UPDATE",
                        "fact_id": new_fact.id,
                        "previous_id": old_id,
                        "similarity": best_similarity,
                    },
                    source="memvault",
                )
            )
            return AttitudeEvolveResult(
                operation="UPDATE",
                fact_id=new_fact.id,
                message=f"Updated existing fact (similarity={best_similarity:.2f}).",
                previous_id=old_id,
            )

        # ADD — new distinct fact
        new_fact = AttitudeFact(
            space_id=space_id,
            fact=request.fact,
            category=request.category,
            operation="ADD",
            confidence=0.5,
            source_sessions=([request.source_session] if request.source_session else []),
            embedding=new_embedding,
        )
        db.add(new_fact)
        await db.flush()

        event_bus.publish_fire_and_forget(
            Event(
                type=MemvaultEvents.ATTITUDE_EVOLVED,
                data={
                    "space_id": space_id,
                    "operation": "ADD",
                    "fact_id": new_fact.id,
                    "similarity": best_similarity,
                },
                source="memvault",
            )
        )
        return AttitudeEvolveResult(
            operation="ADD",
            fact_id=new_fact.id,
            message="New attitude fact added.",
            previous_id=None,
        )

    async def semantic_search(
        self,
        db: AsyncSession,
        space_id: str,
        query: str,
        top_k: int = 3,
    ) -> list[dict]:
        """Semantic search on current attitude facts — Qdrant primary, ILIKE fallback.

        Returns dicts with fact, category, confidence, score for autoRecall injection.
        """
        query_embedding = await get_embedding(query)

        if query_embedding:
            from src.shared.qdrant_client import is_available as qdrant_available
            from src.shared.qdrant_search import vector_search
            from src.shared.search_types import SearchConfig

            if await qdrant_available():
                config = SearchConfig(
                    top_k=top_k,
                    score_threshold=0.4,
                    service_ids=["memvault-attitude"],
                )
                results = await vector_search(query_embedding, space_id, config)
                if results:
                    fact_ids = [r.entity_id for r in results]
                    scores = {r.entity_id: r.score for r in results}
                    q = select(AttitudeFact).where(
                        AttitudeFact.id.in_(fact_ids),
                        AttitudeFact.superseded_by.is_(None),
                        AttitudeFact.deleted_at.is_(None),
                    )
                    rows = (await db.execute(q)).scalars().all()
                    id_order = {eid: i for i, eid in enumerate(fact_ids)}
                    rows = sorted(rows, key=lambda r: id_order.get(str(r.id), 999))
                    return [
                        {
                            "fact": r.fact,
                            "category": r.category,
                            "confidence": r.confidence,
                            "score": round(scores.get(str(r.id), 0.0), 3),
                        }
                        for r in rows
                    ]

        # ILIKE fallback when embedding service unavailable
        q = (
            select(AttitudeFact)
            .where(
                AttitudeFact.space_id == space_id,
                AttitudeFact.superseded_by.is_(None),
                AttitudeFact.deleted_at.is_(None),
                AttitudeFact.fact.ilike(f"%{query}%"),
            )
            .order_by(AttitudeFact.confidence.desc())
            .limit(top_k)
        )
        rows = (await db.execute(q)).scalars().all()
        return [
            {
                "fact": r.fact,
                "category": r.category,
                "confidence": r.confidence,
                "score": 0.0,
            }
            for r in rows
        ]

    async def get_history(self, db: AsyncSession, fact_id: str) -> list[AttitudeFactResponse]:
        """Trace the full evolution history of an attitude fact.

        Follows the previous_version chain from the given fact backward.
        """
        history: list[AttitudeFactResponse] = []
        current_id: str | None = fact_id

        while current_id is not None:
            fact = await db.get(AttitudeFact, current_id)
            if not fact:
                break
            history.append(self.to_response(fact))
            current_id = fact.previous_version

        return history

    async def delete_by_id(self, db: AsyncSession, id: str) -> None:
        result = await db.execute(select(AttitudeFact).where(AttitudeFact.id == id))
        instance = result.scalar_one_or_none()
        if not instance:
            raise NotFoundError("Attitude fact not found", code="memvault.attitude_not_found")
        await db.delete(instance)

    async def update_by_id(
        self, db: AsyncSession, id: str, data: AttitudeFactCreate
    ) -> AttitudeFact:
        result = await db.execute(select(AttitudeFact).where(AttitudeFact.id == id))
        instance = result.scalar_one_or_none()
        if not instance:
            raise NotFoundError("Attitude fact not found", code="memvault.attitude_not_found")
        d = data.model_dump(exclude_unset=True)
        for key, val in d.items():
            setattr(instance, key, val)
        return instance


# ======================== SkillTrackingService ========================


class SkillTrackingService:
    """Record and aggregate skill invocations (standalone)."""

    def to_response(self, instance: SkillInvocation) -> SkillInvocationResponse:
        """Convert ORM SkillInvocation to SkillInvocationResponse."""
        return SkillInvocationResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            skill_name=instance.skill_name,
            source_session=instance.source_session,
            cwd=instance.cwd,
            invoked_at=instance.invoked_at,
            outcome=instance.outcome,
            duration_ms=instance.duration_ms,
        )

    async def record_invocation(
        self,
        db: AsyncSession,
        space_id: str,
        data: SkillInvocationCreate,
    ) -> SkillInvocation:
        """Record a skill invocation, skipping duplicates gracefully."""
        invocation = SkillInvocation(
            space_id=space_id,
            skill_name=data.skill_name,
            source_session=data.source_session,
            cwd=data.cwd,
            invoked_at=data.invoked_at,
            outcome=data.outcome,
            duration_ms=data.duration_ms,
        )
        db.add(invocation)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            logger.debug(
                "Skipping duplicate skill invocation: %s (session=%s, at=%s)",
                data.skill_name,
                data.source_session,
                data.invoked_at,
            )
            # Return existing record
            q = select(SkillInvocation).where(
                SkillInvocation.space_id == space_id,
                SkillInvocation.skill_name == data.skill_name,
                SkillInvocation.source_session == data.source_session,
                SkillInvocation.invoked_at == data.invoked_at,
            )
            invocation = (await db.execute(q)).scalar_one()

        event_bus.publish_fire_and_forget(
            Event(
                type=MemvaultEvents.SKILL_INVOKED,
                data={
                    "space_id": space_id,
                    "skill_name": data.skill_name,
                    "outcome": data.outcome,
                    "source_session": data.source_session,
                },
                source="memvault",
            )
        )
        return invocation

    async def get_proficiency(
        self, db: AsyncSession, space_id: str
    ) -> list[SkillProficiencyResponse]:
        """Aggregate skill proficiency from invocation records.

        Proficiency = invocation_count * success_rate * recency_factor
        where recency_factor = max(0.1, 1.0 - days_since_last / 90).
        """
        q = (
            select(
                SkillInvocation.skill_name,
                func.count().label("invocation_count"),
                func.sum(
                    case(
                        (SkillInvocation.outcome == "success", 1),
                        else_=0,
                    )
                ).label("success_count"),
                func.max(SkillInvocation.invoked_at).label("last_invoked"),
            )
            .where(SkillInvocation.space_id == space_id)
            .group_by(SkillInvocation.skill_name)
        )
        rows = (await db.execute(q)).all()

        now = datetime.now(UTC)
        results: list[SkillProficiencyResponse] = []
        for row in rows:
            invocation_count: int = row.invocation_count
            success_count: int = row.success_count or 0
            last_invoked = row.last_invoked
            success_rate = success_count / invocation_count if invocation_count > 0 else 0.0

            days_since = (now - last_invoked).days if last_invoked else 90
            recency_factor = max(0.1, 1.0 - days_since / 90)
            proficiency = round(invocation_count * success_rate * recency_factor, 4)

            results.append(
                SkillProficiencyResponse(
                    skill_name=row.skill_name,
                    invocation_count=invocation_count,
                    success_count=success_count,
                    success_rate=round(success_rate, 4),
                    last_invoked=last_invoked,
                    proficiency=proficiency,
                )
            )

        # Sort by proficiency descending
        results.sort(key=lambda r: r.proficiency, reverse=True)
        return results

    async def get_skill_history(
        self,
        db: AsyncSession,
        space_id: str,
        skill_name: str,
        limit: int = 20,
    ) -> list[SkillInvocationResponse]:
        """Return recent invocations for a specific skill, newest first."""
        q = (
            select(SkillInvocation)
            .where(
                SkillInvocation.space_id == space_id,
                SkillInvocation.skill_name == skill_name,
            )
            .order_by(SkillInvocation.invoked_at.desc())
            .limit(limit)
        )
        rows = (await db.execute(q)).scalars().all()
        return [self.to_response(r) for r in rows]

    async def delete_by_id(self, db: AsyncSession, id: str) -> None:
        result = await db.execute(select(SkillInvocation).where(SkillInvocation.id == id))
        instance = result.scalar_one_or_none()
        if not instance:
            raise NotFoundError("Skill invocation not found", code="memvault.invocation_not_found")
        await db.delete(instance)


# ======================== CascadeRecallService ========================


class CascadeRecallService:
    """Multi-layer recall: L2 (community summaries) → L1 (communities) → L0 (triples) → blocks.

    Integrates:
      - Phase 1: Qdrant semantic search for L1/L2 with ILIKE fallback
      - Phase 2: Adaptive query router for layer selection
      - Phase 3: CRAG evaluator for result quality assessment
    """

    async def recall(
        self,
        db: AsyncSession,
        space_id: str,
        query: str,
        top_k: int = 5,
        skip_routing: bool = False,
        evaluate: str = "default",
    ) -> CascadeRecallResult:
        """Cascade recall across all KG layers plus memory blocks.

        Args:
            skip_routing: If True, search all layers (bypass query router).
            evaluate: CRAG evaluation depth — "default" (Layer A+B), "deep" (+Haiku),
                      "rlm" (+RLM query decomposition), "none" (skip evaluation).
        """
        from .services import memory_block_service

        result = CascadeRecallResult()
        query_embedding = await get_embedding(query)
        pattern = f"%{query}%"

        # --- Phase 5: Personalized Query Router ---
        layer_plan = None
        if not skip_routing:
            try:
                from .query_router import PersonalizedQueryRouter

                attention = await self._get_cached_attention(db, space_id)
                router = PersonalizedQueryRouter(attention)
                layer_plan = router.classify(query)
                result.routing_intent = layer_plan.intent.value
                result.routing_confidence = layer_plan.confidence
            except Exception as e:
                logger.warning("Query router failed (searching all layers): %s", e)

        # Helper: check if a layer should be searched
        def _should_search(layer: str) -> bool:
            if layer_plan is None:
                return True  # no routing → search all
            return layer_plan.layers.get(layer, "SKIP") != "SKIP"

        def _search_mode(layer: str) -> str:
            if layer_plan is None:
                return "HYBRID"
            return layer_plan.layers.get(layer, "SKIP")

        # --- L2: CommunitySummary (Qdrant semantic → ILIKE fallback) ---
        if _should_search("summaries"):
            summary_rows = await self._search_summaries_semantic(
                db, space_id, query, top_k, _search_mode("summaries")
            )
            if not summary_rows:
                summary_rows = await self._search_summaries_ilike(db, space_id, pattern, top_k)
            if summary_rows:
                result.summaries = [community_summary_service.to_response(r) for r in summary_rows]
                result.layers_searched.append("summaries")

        # --- L1: Communities (Qdrant semantic → ILIKE fallback) ---
        if _should_search("communities"):
            community_rows = await self._search_communities_semantic(
                db, space_id, query, top_k, _search_mode("communities")
            )
            if not community_rows:
                community_rows = await self._search_communities_ilike(db, space_id, pattern, top_k)
            if community_rows:
                result.communities = [community_service.to_response(r) for r in community_rows]
                result.layers_searched.append("communities")

        # --- L0: Triples (semantic or text) ---
        if _should_search("triples"):
            if query_embedding:
                triple_results = await triple_service.semantic_search(
                    db, space_id, query_embedding, top_k=top_k
                )
            else:
                triple_q = (
                    select(Triple)
                    .where(
                        Triple.space_id == space_id,
                        (
                            Triple.subject.ilike(pattern)
                            | Triple.object.ilike(pattern)
                            | Triple.topic.ilike(pattern)
                        ),
                    )
                    .limit(top_k)
                )
                triple_rows = (await db.execute(triple_q)).scalars().all()
                triple_results = [triple_service.to_response(r) for r in triple_rows]

            if triple_results:
                result.triples = triple_results
                result.layers_searched.append("triples")

        # --- Blocks: semantic or text search ---
        if _should_search("blocks"):
            if query_embedding:
                search_results, _meta = await memory_block_service.semantic_search(
                    db, space_id, query_embedding, top_k=top_k
                )
                blocks = [sr.block for sr in search_results]
            else:
                search_results = await memory_block_service.text_search(
                    db, space_id, query, top_k=top_k
                )
                blocks = [sr.block for sr in search_results]

            if blocks:
                result.blocks = blocks
                result.layers_searched.append("blocks")

        # --- Phase 2: Empty-result retry with full scan ---
        if layer_plan is not None and not skip_routing and not result.layers_searched:
            logger.info("Routed recall returned empty — retrying with full scan")
            return await self.recall(
                db,
                space_id,
                query,
                top_k=top_k,
                skip_routing=True,
                evaluate=evaluate,
            )

        # --- Phase 3: CRAG Evaluator ---
        if evaluate != "none":
            try:
                from .crag_evaluator import CRAGEvaluator

                evaluator = CRAGEvaluator()
                evaluation = await evaluator.evaluate(query, result, evaluate=evaluate)
                result.confidence_score = evaluation.confidence_score
                result.evaluation_verdict = evaluation.verdict.value
                result.evaluation_metadata = evaluation.metadata
            except Exception as e:
                logger.warning("CRAG evaluation failed (non-fatal): %s", e)

        # --- Closed-Loop: Record access + implicit feedback + query journal (fire-and-forget) ---
        import asyncio

        bg_tasks: list[asyncio.Task] = []
        bg_tasks.append(asyncio.ensure_future(self._record_recall_access(result)))
        if result.evaluation_verdict:
            bg_tasks.append(
                asyncio.ensure_future(self._record_implicit_feedback(space_id, query, result))
            )
        bg_tasks.append(
            asyncio.ensure_future(self._record_query_journal(space_id, query, result))
        )

        # --- Closed-Loop: Rerank by access count ---
        result.triples = self._rerank_by_access(result.triples)
        result.communities = self._rerank_by_access(result.communities)

        return result

    # --- L2 semantic search helpers ---

    async def _search_summaries_semantic(
        self,
        db: AsyncSession,
        space_id: str,
        query: str,
        top_k: int,
        mode: str,
    ) -> list[CommunitySummary]:
        """Search L2 summaries via Qdrant. Returns ORM objects."""
        if mode == "ILIKE":
            return []  # caller will use ILIKE path

        try:
            from src.shared.qdrant_search import search_with_fallback

            results, meta = await search_with_fallback(
                query,
                space_id,
                "memvault-summary",
                top_k=top_k,
            )
            if meta.backend == "ilike_fallback" or not results:
                return []
            # Fetch ORM objects by IDs
            ids = [r.entity_id for r in results]
            rows = (
                (await db.execute(select(CommunitySummary).where(CommunitySummary.id.in_(ids))))
                .scalars()
                .all()
            )
            # Preserve Qdrant ranking order
            id_order = {eid: i for i, eid in enumerate(ids)}
            rows.sort(key=lambda r: id_order.get(str(r.id), 999))
            return list(rows)
        except Exception as e:
            logger.debug("L2 Qdrant search failed, falling back to ILIKE: %s", e)
            return []

    async def _search_summaries_ilike(
        self,
        db: AsyncSession,
        space_id: str,
        pattern: str,
        top_k: int,
    ) -> list[CommunitySummary]:
        q = (
            select(CommunitySummary)
            .where(
                CommunitySummary.space_id == space_id,
                CommunitySummary.summary.ilike(pattern),
            )
            .limit(top_k)
        )
        return list((await db.execute(q)).scalars().all())

    # --- L1 semantic search helpers ---

    async def _search_communities_semantic(
        self,
        db: AsyncSession,
        space_id: str,
        query: str,
        top_k: int,
        mode: str,
    ) -> list[Community]:
        """Search L1 communities via Qdrant. Returns ORM objects."""
        if mode == "ILIKE":
            return []

        try:
            from src.shared.qdrant_search import search_with_fallback

            results, meta = await search_with_fallback(
                query,
                space_id,
                "memvault-community",
                top_k=top_k,
            )
            if meta.backend == "ilike_fallback" or not results:
                return []
            ids = [r.entity_id for r in results]
            rows = (
                (await db.execute(select(Community).where(Community.id.in_(ids)))).scalars().all()
            )
            id_order = {eid: i for i, eid in enumerate(ids)}
            rows.sort(key=lambda r: id_order.get(str(r.id), 999))
            return list(rows)
        except Exception as e:
            logger.debug("L1 Qdrant search failed, falling back to ILIKE: %s", e)
            return []

    async def _search_communities_ilike(
        self,
        db: AsyncSession,
        space_id: str,
        pattern: str,
        top_k: int,
    ) -> list[Community]:
        q = (
            select(Community)
            .where(
                Community.space_id == space_id,
                (Community.summary.ilike(pattern) | Community.name.ilike(pattern)),
            )
            .order_by(Community.size.desc())
            .limit(top_k)
        )
        return list((await db.execute(q)).scalars().all())

    # --- Closed-Loop Learning helpers ---

    async def _record_recall_access(self, result: CascadeRecallResult) -> None:
        """Increment access_count on all triples and communities returned by recall.

        Uses its own DB session (fire-and-forget safe — request session may close).
        """
        from src.shared.database import async_session_factory

        triple_ids = [t.id for t in result.triples if t.id]
        community_ids = [c.id for c in result.communities if c.id]
        if not triple_ids and not community_ids:
            return

        try:
            now = datetime.now(UTC)
            async with async_session_factory() as db:
                if triple_ids:
                    await db.execute(
                        update(Triple)
                        .where(Triple.id.in_(triple_ids))
                        .values(
                            access_count=Triple.access_count + 1,
                            last_accessed_at=now,
                        )
                    )
                if community_ids:
                    await db.execute(
                        update(Community)
                        .where(Community.id.in_(community_ids))
                        .values(
                            access_count=Community.access_count + 1,
                            last_accessed_at=now,
                        )
                    )
                await db.commit()
            logger.debug(
                "Recall access recorded: %d triples, %d communities",
                len(triple_ids),
                len(community_ids),
            )
        except Exception:
            logger.warning("Failed to record recall access", exc_info=True)

    async def _record_implicit_feedback(
        self,
        space_id: str,
        query: str,
        result: CascadeRecallResult,
    ) -> None:
        """Record implicit feedback from CRAG verdict into search_feedback table.

        CORRECT → positive signal for all returned entities.
        INCORRECT → negative signal for all returned entities.
        AMBIGUOUS → skip (not enough signal).
        Uses its own DB session (fire-and-forget safe — request session may close).
        """
        verdict = result.evaluation_verdict
        if verdict == "AMBIGUOUS":
            return

        signal = "positive" if verdict == "CORRECT" else "negative"

        entity_ids: list[str] = []
        entity_ids.extend(t.id for t in result.triples if t.id)
        entity_ids.extend(c.id for c in result.communities if c.id)
        for b in result.blocks:
            bid = b.get("id") if isinstance(b, dict) else getattr(b, "id", None)
            if bid:
                entity_ids.append(bid)

        if not entity_ids:
            return

        try:
            from src.shared.database import async_session_factory

            from .services import search_feedback_service

            async with async_session_factory() as db:
                await search_feedback_service.record_implicit_batch(
                    db, space_id, entity_ids, query, signal
                )
                await db.commit()
            logger.debug(
                "Implicit feedback recorded: verdict=%s signal=%s entities=%d",
                verdict,
                signal,
                len(entity_ids),
            )
        except Exception:
            logger.warning("Failed to record implicit feedback", exc_info=True)

    async def _record_query_journal(
        self,
        space_id: str,
        query: str,
        result: CascadeRecallResult,
    ) -> None:
        """Record a query journal entry (fire-and-forget, own session)."""
        import hashlib

        try:
            from src.shared.database import async_session_factory

            from .models import QueryJournal

            query_hash = hashlib.sha256(query.encode()).hexdigest()

            # Collect top entity IDs (first 5 from triples + communities)
            top_ids: list[str] = []
            for t in result.triples[:3]:
                if t.id:
                    top_ids.append(t.id)
            for c in result.communities[:2]:
                if c.id:
                    top_ids.append(c.id)

            total_results = (
                len(result.triples) + len(result.communities)
                + len(result.summaries) + len(result.blocks)
            )

            async with async_session_factory() as db:
                entry = QueryJournal(
                    space_id=space_id,
                    query_text=query,
                    query_hash=query_hash,
                    routing_intent=result.routing_intent,
                    routing_confidence=result.routing_confidence,
                    layers_searched=result.layers_searched or [],
                    result_count=total_results,
                    evaluation_verdict=result.evaluation_verdict,
                    evaluation_score=result.confidence_score,
                    top_entity_ids=top_ids,
                )
                db.add(entry)
                await db.commit()
            logger.debug(
                "Query journal recorded: hash=%s results=%d", query_hash[:12], total_results
            )
        except Exception:
            logger.warning("Failed to record query journal", exc_info=True)

    async def _get_cached_attention(self, db: AsyncSession, space_id: str) -> dict | None:
        """Get attention profile with Redis caching (30 min TTL)."""
        from src.shared.cache import cache_get, cache_set

        cache_key = f"cache:memvault:attention_profile:{space_id}"
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            from .interest_profile import interest_profile_service

            profile = await interest_profile_service.get_attention_profile(db, space_id)
            if profile:
                await cache_set(cache_key, profile, ttl=1800)  # 30 min
            return profile
        except Exception:
            logger.debug("Failed to load attention profile", exc_info=True)
            return None

    @staticmethod
    def _rerank_by_access(items: list) -> list:
        """Stable rerank: boost items with higher access_count to the front.

        Uses access_count as a secondary sort key (descending) while preserving
        the original semantic ranking as the primary key.
        """
        if not items or len(items) <= 1:
            return items

        indexed = list(enumerate(items))
        indexed.sort(key=lambda pair: (-getattr(pair[1], "access_count", 0), pair[0]))
        return [item for _, item in indexed]


# ======================== Confidence Decay ========================


class ConfidenceDecayService:
    """Apply time-based confidence decay to triples and attitude facts.

    Uses exponential half-life decay per category:
        confidence = original * 0.5 ^ (days_since_update / half_life_days)

    Minimum confidence floor: 0.05 (knowledge never reaches zero).
    Only writes rows where the decayed value differs by > 0.01 from stored value.
    """

    # Half-life in days by attitude category
    DECAY_RATES: dict[str, float] = {
        "technical": 180,  # 6 months
        "preference": 90,  # 3 months
        "principle": 36500,  # ~100 years (effectively permanent)
        "workflow": 120,  # 4 months
        "tool_behavior": 150,  # 5 months
        "config": 120,  # 4 months
        "architecture": 365,  # 1 year
        "default": 180,  # fallback
    }

    CONFIDENCE_FLOOR = 0.05

    async def apply_decay(self, db: AsyncSession, space_id: str) -> dict:
        """Apply exponential decay to all current attitude facts in the space.

        Returns:
            {"attitudes_updated": N, "attitudes_checked": M}
        """
        now = datetime.now(UTC)

        # Fetch all non-superseded attitude facts for the space
        stmt = select(AttitudeFact).where(
            AttitudeFact.space_id == space_id,
            AttitudeFact.superseded_by.is_(None),
        )
        result = await db.execute(stmt)
        facts = result.scalars().all()

        attitudes_checked = len(facts)
        attitudes_updated = 0

        for fact in facts:
            # Determine time elapsed since last update
            updated_at = fact.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
            days = (now - updated_at).total_seconds() / 86400

            half_life = self.DECAY_RATES.get(
                fact.category or "default", self.DECAY_RATES["default"]
            )
            decayed = fact.confidence * (0.5 ** (days / half_life))
            decayed = max(decayed, self.CONFIDENCE_FLOOR)

            if abs(decayed - fact.confidence) > 0.01:
                await db.execute(
                    update(AttitudeFact)
                    .where(AttitudeFact.id == fact.id)
                    .values(confidence=round(decayed, 4))
                )
                attitudes_updated += 1

        logger.info(
            "Confidence decay applied: space=%s checked=%d updated=%d",
            space_id,
            attitudes_checked,
            attitudes_updated,
        )
        return {
            "attitudes_updated": attitudes_updated,
            "attitudes_checked": attitudes_checked,
        }


# ======================== SkillProfileService ========================


class SkillProfileService:
    """Manage per-skill proficiency profiles (KAS Skill dimension)."""

    def to_response(self, instance: SkillProfile) -> SkillProfileResponse:
        return SkillProfileResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            skill_name=instance.skill_name,
            total_uses=instance.total_uses,
            recent_uses=instance.recent_uses,
            success_rate=instance.success_rate,
            avg_duration_ms=instance.avg_duration_ms,
            auto_rate=instance.auto_rate,
            common_patterns=instance.common_patterns,
            learned_preferences=instance.learned_preferences,
            pitfalls=instance.pitfalls,
            proficiency_level=instance.proficiency_level,
            health_score=instance.health_score,
            evolution_notes=instance.evolution_notes,
            last_synced_at=instance.last_synced_at,
        )

    async def upsert(
        self,
        db: AsyncSession,
        space_id: str,
        skill_name: str,
        data: SkillProfileUpsert,
    ) -> SkillProfile:
        """Create or update a skill profile by skill_name + space_id."""
        q = select(SkillProfile).where(
            SkillProfile.space_id == space_id,
            SkillProfile.skill_name == skill_name,
        )
        existing = (await db.execute(q)).scalar_one_or_none()

        if existing:
            update_data = data.model_dump(exclude_unset=True, exclude={"skill_name"})
            for key, val in update_data.items():
                if val is not None:
                    setattr(existing, key, val)
            existing.last_synced_at = datetime.now(UTC)
            await db.flush()
            return existing

        # Create new
        profile = SkillProfile(
            space_id=space_id,
            skill_name=skill_name,
            last_synced_at=datetime.now(UTC),
        )
        create_data = data.model_dump(exclude_unset=True, exclude={"skill_name"})
        for key, val in create_data.items():
            if val is not None:
                setattr(profile, key, val)
        db.add(profile)
        await db.flush()
        return profile

    async def get_all(
        self, db: AsyncSession, space_id: str
    ) -> list[SkillProfileResponse]:
        q = (
            select(SkillProfile)
            .where(SkillProfile.space_id == space_id)
            .order_by(SkillProfile.total_uses.desc())
        )
        rows = (await db.execute(q)).scalars().all()
        return [self.to_response(r) for r in rows]

    async def get_by_skill(
        self, db: AsyncSession, space_id: str, skill_name: str
    ) -> SkillProfileResponse | None:
        q = select(SkillProfile).where(
            SkillProfile.space_id == space_id,
            SkillProfile.skill_name == skill_name,
        )
        instance = (await db.execute(q)).scalar_one_or_none()
        if not instance:
            return None
        return self.to_response(instance)


# ======================== Module-level singletons ========================

triple_service = TripleService()
community_service = CommunityService()
community_summary_service = CommunitySummaryService()
attitude_service = AttitudeService()
skill_tracking_service = SkillTrackingService()
skill_profile_service = SkillProfileService()
cascade_recall_service = CascadeRecallService()
confidence_decay_service = ConfidenceDecayService()
graph_traversal_service = GraphTraversalService()

"""Memvault KG Services — Triple, Cluster, Wisdom, Attitude, Skill, CascadeRecall.

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
    Cluster,
    ClusterTriple,
    SkillInvocation,
    Triple,
    TripleEmbedding,
    WisdomNode,
)
from .kg_schemas import (
    AttitudeEvolveRequest,
    AttitudeEvolveResult,
    AttitudeFactCreate,
    AttitudeFactResponse,
    CascadeRecallResult,
    ClusterDetail,
    ClusterResponse,
    GraphEdge,
    GraphNode,
    GraphTraversalResult,
    SkillInvocationCreate,
    SkillInvocationResponse,
    SkillProficiencyResponse,
    TripleBatchCreate,
    TripleCreate,
    TripleResponse,
    WisdomNodeResponse,
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

    def before_create(self, data: TripleCreate, **kwargs: Any) -> dict:
        """Normalize predicate and entity text before inserting."""
        d = data.model_dump()
        d["predicate"] = normalize_predicate(d["predicate"])
        d["subject"] = normalize_entity_text(d["subject"])
        d["object"] = normalize_entity_text(d["object"])
        return d

    def after_create(self, instance: Triple) -> None:
        """Publish TRIPLE_INGESTED event (fire-and-forget)."""
        import asyncio

        asyncio.ensure_future(  # noqa: RUF006
            event_bus.publish(
                Event(
                    type=MemvaultEvents.TRIPLE_INGESTED,
                    data={
                        "triple_id": instance.id,
                        "subject": instance.subject,
                        "predicate": instance.predicate,
                        "source_session": instance.source_session,
                    },
                    source="memvault",
                    user_id=instance.created_by,
                )
            )
        )

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

            # Best-effort embedding
            embedding_text = f"{subject} {predicate} {object_text}"
            embedding = await get_embedding(embedding_text)

            triple = Triple(
                space_id=space_id,
                source_session=batch.session_id,
                subject=subject,
                predicate=predicate,
                object=object_text,
                topic=topic,
                timestamp=timestamp,
                embedding=embedding,
            )
            db.add(triple)
            try:
                await db.flush()
                # Write to embedding sub-table (Phase 2)
                if embedding is not None:
                    db.add(TripleEmbedding(triple_id=triple.id, embedding=embedding))
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
            event_bus.publish(
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
        """Vector similarity search on triples using pgvector cosine distance.

        Tries triple_embeddings sub-table first (Phase 2);
        falls back to inline triples.embedding.
        """
        # Phase 2 path: sub-table
        distance = TripleEmbedding.embedding.cosine_distance(query_embedding)
        q = (
            select(Triple)
            .join(TripleEmbedding, TripleEmbedding.triple_id == Triple.id)
            .where(
                Triple.space_id == space_id,
                Triple.invalid_at.is_(None),
                distance < (1 - threshold),
            )
            .order_by(distance)
            .limit(top_k)
        )
        rows = (await db.execute(q)).scalars().all()
        if rows:
            return [self.to_response(r) for r in rows]

        # Fallback: inline embedding
        distance = Triple.embedding.cosine_distance(query_embedding)
        q = (
            select(Triple)
            .where(
                Triple.space_id == space_id,
                Triple.embedding.isnot(None),
                Triple.invalid_at.is_(None),
                distance < (1 - threshold),
            )
            .order_by(distance)
            .limit(top_k)
        )
        rows = (await db.execute(q)).scalars().all()
        return [self.to_response(r) for r in rows]

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

        event_bus.publish(
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
        if new_triple.embedding is None:
            return []

        distance = Triple.embedding.cosine_distance(new_triple.embedding)
        q = (
            select(Triple)
            .where(
                Triple.space_id == space_id,
                Triple.id != new_triple.id,
                Triple.invalid_at.is_(None),
                Triple.subject == new_triple.subject,
                Triple.predicate == new_triple.predicate,
                Triple.embedding.isnot(None),
                distance < (1 - similarity_threshold),
            )
            .order_by(distance)
            .limit(5)
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


# ======================== ClusterService ========================


class ClusterService:
    """Manage L1 Cluster records (standalone — no BaseCRUD)."""

    def to_response(self, instance: Cluster) -> ClusterResponse:
        """Map ORM Cluster to ClusterResponse."""
        return ClusterResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            name=instance.name,
            size=instance.size,
            top_subjects=instance.top_subjects or [],
            top_predicates=instance.top_predicates or [],
            top_objects=instance.top_objects or [],
            summary=instance.summary,
            verdict=instance.verdict,
            generation_batch=instance.generation_batch,
        )

    async def list_clusters(self, db: AsyncSession, space_id: str) -> list[ClusterResponse]:
        """List all clusters for a space, ordered by size descending."""
        q = select(Cluster).where(Cluster.space_id == space_id).order_by(Cluster.size.desc())
        rows = (await db.execute(q)).scalars().all()
        return [self.to_response(r) for r in rows]

    async def get_cluster_detail(self, db: AsyncSession, cluster_id: str) -> ClusterDetail | None:
        """Get a cluster with its member triples via cluster_triples join."""
        cluster = await db.get(Cluster, cluster_id)
        if not cluster:
            return None

        # Fetch member triples via join
        q = (
            select(Triple)
            .join(ClusterTriple, ClusterTriple.triple_id == Triple.id)
            .where(ClusterTriple.cluster_id == cluster_id)
            .order_by(ClusterTriple.confidence.desc())
        )
        triple_rows = (await db.execute(q)).scalars().all()
        triple_svc = triple_service  # use module-level singleton

        return ClusterDetail(
            id=cluster.id,
            space_id=cluster.space_id,
            created_by=cluster.created_by,
            created_at=cluster.created_at,
            updated_at=cluster.updated_at,
            name=cluster.name,
            size=cluster.size,
            top_subjects=cluster.top_subjects or [],
            top_predicates=cluster.top_predicates or [],
            top_objects=cluster.top_objects or [],
            summary=cluster.summary,
            verdict=cluster.verdict,
            generation_batch=cluster.generation_batch,
            triples=[triple_svc.to_response(t) for t in triple_rows],
        )

    async def save_clusters(
        self,
        db: AsyncSession,
        space_id: str,
        clusters_data: list[dict],
    ) -> int:
        """Atomically replace all clusters for a space with fresh GMM results.

        Deletes existing clusters and cluster_triples, inserts new ones.
        Returns count of clusters saved.
        """
        # Delete existing cluster_triples then clusters for this space
        existing_cluster_ids = (
            select(Cluster.id).where(Cluster.space_id == space_id).scalar_subquery()
        )
        await db.execute(
            delete(ClusterTriple).where(ClusterTriple.cluster_id.in_(existing_cluster_ids))
        )
        await db.execute(delete(Cluster).where(Cluster.space_id == space_id))

        saved = 0
        for c in clusters_data:
            cluster = Cluster(
                space_id=space_id,
                name=c.get("name", ""),
                size=c.get("size", 0),
                top_subjects=c.get("top_subjects"),
                top_predicates=c.get("top_predicates"),
                top_objects=c.get("top_objects"),
                summary=c.get("summary"),
                verdict=c.get("verdict", "UNVERIFIED"),
                generation_batch=c.get("generation_batch"),
            )
            db.add(cluster)
            await db.flush()

            for member in c.get("members", []):
                # member = {"triple_id": ..., "confidence": ...}
                ct = ClusterTriple(
                    space_id=space_id,
                    cluster_id=cluster.id,
                    triple_id=member["triple_id"],
                    confidence=member.get("confidence"),
                )
                db.add(ct)

            saved += 1

        await db.flush()

        event_bus.publish(
            Event(
                type=MemvaultEvents.CLUSTER_REGENERATED,
                data={"space_id": space_id, "count": saved},
                source="memvault",
            )
        )
        return saved


# ======================== WisdomService ========================


class WisdomService:
    """Manage L2 WisdomNode records (standalone)."""

    def to_response(self, instance: WisdomNode) -> WisdomNodeResponse:
        """Map ORM WisdomNode to WisdomNodeResponse."""
        return WisdomNodeResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            wisdom=instance.wisdom,
            confidence=instance.confidence,
            bridge_entity=instance.bridge_entity,
            cluster_ids=instance.cluster_ids or [],
            evidence_count=instance.evidence_count,
            tags=instance.tags or [],
            verified=instance.verified,
        )

    async def list_wisdoms(
        self,
        db: AsyncSession,
        space_id: str,
        confidence_min: str | None = None,
        tag: str | None = None,
    ) -> list[WisdomNodeResponse]:
        """List wisdom nodes, optionally filtered by confidence level or tag."""
        q = select(WisdomNode).where(WisdomNode.space_id == space_id)

        if confidence_min is not None:
            # Order: HIGH > MEDIUM > LOW — filter by minimum level
            level_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
            min_rank = level_order.get(confidence_min.upper(), 1)
            allowed = [k for k, v in level_order.items() if v >= min_rank]
            q = q.where(WisdomNode.confidence.in_(allowed))

        if tag is not None:
            q = q.where(WisdomNode.tags.contains([tag]))

        rows = (await db.execute(q)).scalars().all()
        return [self.to_response(r) for r in rows]

    async def save_wisdoms(
        self,
        db: AsyncSession,
        space_id: str,
        wisdoms_data: list[dict],
    ) -> int:
        """Atomically replace all wisdom nodes for a space.

        Deletes existing wisdom_nodes, inserts new ones.
        Returns count saved.
        """
        await db.execute(delete(WisdomNode).where(WisdomNode.space_id == space_id))

        saved = 0
        for w in wisdoms_data:
            node = WisdomNode(
                space_id=space_id,
                wisdom=w["wisdom"],
                confidence=w.get("confidence", "MEDIUM"),
                bridge_entity=w.get("bridge_entity", ""),
                cluster_ids=w.get("cluster_ids", []),
                evidence_count=w.get("evidence_count"),
                tags=w.get("tags"),
                verified=w.get("verified", False),
            )
            db.add(node)
            saved += 1

        await db.flush()

        event_bus.publish(
            Event(
                type=MemvaultEvents.WISDOM_REGENERATED,
                data={"space_id": space_id, "count": saved},
                source="memvault",
            )
        )
        return saved


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
            AttitudeFact.embedding.isnot(None),
        )
        current_facts = (await db.execute(q)).scalars().all()

        best_fact: AttitudeFact | None = None
        best_similarity: float = 0.0

        if new_embedding and current_facts:
            # Use pgvector cosine_distance operator (<=>) to find closest fact
            distance_col = AttitudeFact.embedding.cosine_distance(new_embedding).label("distance")
            sim_q = (
                select(AttitudeFact, distance_col)
                .where(
                    AttitudeFact.space_id == space_id,
                    AttitudeFact.category == request.category,
                    AttitudeFact.superseded_by.is_(None),
                    AttitudeFact.embedding.isnot(None),
                )
                .order_by(distance_col)
                .limit(1)
            )
            row = (await db.execute(sim_q)).first()
            if row:
                best_fact = row.AttitudeFact
                best_similarity = round(1.0 - float(row.distance), 4)

        # Decision logic
        if best_fact and best_similarity > 0.9:
            # NOOP — bump confidence on existing fact
            best_fact.confidence = min(1.0, best_fact.confidence + 0.05)
            await db.flush()
            event_bus.publish(
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

            event_bus.publish(
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

        event_bus.publish(
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

        event_bus.publish(
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
    """Multi-layer recall: L2 (wisdom) → L1 (clusters) → L0 (triples) → blocks."""

    async def recall(
        self,
        db: AsyncSession,
        space_id: str,
        query: str,
        top_k: int = 5,
    ) -> CascadeRecallResult:
        """Cascade recall across all KG layers plus memory blocks.

        Attempts semantic search when embeddings are available; falls back to
        ILIKE text search otherwise.
        """
        # Lazy import to avoid circular dependency
        from .services import memory_block_service

        result = CascadeRecallResult()
        query_embedding = await get_embedding(query)
        pattern = f"%{query}%"

        # --- L2: Wisdom nodes (text ILIKE — no embeddings on wisdom_nodes) ---
        wisdom_q = (
            select(WisdomNode)
            .where(
                WisdomNode.space_id == space_id,
                WisdomNode.wisdom.ilike(pattern),
            )
            .limit(top_k)
        )
        wisdom_rows = (await db.execute(wisdom_q)).scalars().all()
        if wisdom_rows:
            result.wisdom = [wisdom_service.to_response(r) for r in wisdom_rows]
            result.layers_searched.append("wisdom")

        # --- L1: Clusters (summary ILIKE) ---
        cluster_q = (
            select(Cluster)
            .where(
                Cluster.space_id == space_id,
                Cluster.summary.ilike(pattern),
            )
            .order_by(Cluster.size.desc())
            .limit(top_k)
        )
        cluster_rows = (await db.execute(cluster_q)).scalars().all()
        if cluster_rows:
            result.clusters = [cluster_service.to_response(r) for r in cluster_rows]
            result.layers_searched.append("clusters")

        # --- L0: Triples (semantic or text) ---
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
        if query_embedding:
            block_results = await memory_block_service.semantic_search(
                db, space_id, query_embedding, top_k=top_k
            )
            blocks = [sr.block for sr in block_results]
        else:
            block_results = await memory_block_service.text_search(db, space_id, query, top_k=top_k)
            blocks = [sr.block for sr in block_results]

        if blocks:
            result.blocks = blocks
            result.layers_searched.append("blocks")

        return result


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


# ======================== Module-level singletons ========================

triple_service = TripleService()
cluster_service = ClusterService()
wisdom_service = WisdomService()
attitude_service = AttitudeService()
skill_tracking_service = SkillTrackingService()
cascade_recall_service = CascadeRecallService()
confidence_decay_service = ConfidenceDecayService()
graph_traversal_service = GraphTraversalService()

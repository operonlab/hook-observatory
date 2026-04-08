"""CommunityIndexOp — Leiden clustering + L2 community summary generation.

Builds entity graph from DocTriple records, runs multi-resolution Leiden
community detection, persists DocCommunity / DocCommunityTriple records,
generates LLM summaries for coarse (level-2) communities, and indexes
summaries to Qdrant for semantic search.

Operator protocol:
  input_keys:  ("space_id", "db")           — "document_id" optional scoping
  output_keys: ("community_count", "summary_count")
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import Agent
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from kg_ops import (
    assign_triples_to_communities,
    build_entity_graph,
    build_triple_text,
    run_leiden,
)
from kg_ops.community_prompts import SUMMARY_PROMPT_ZH

from ..kg_models import (
    DocCommunity,
    DocCommunitySummary,
    DocCommunityTriple,
    DocTriple,
)
from ..llm_config import make_model
from ..llm_models import CommunitySummaryResult

logger = logging.getLogger(__name__)

# Minimum triples required to build meaningful communities
MIN_TRIPLES = 5

# Community summary model — intentionally fixed (not dynamic)
SUMMARY_MODEL = "deepseek-v3"

# Community summary Qdrant service identifier
COMMUNITY_SERVICE_ID = "docvault-community"

_community_agent = Agent(
    output_type=CommunitySummaryResult,
    system_prompt=SUMMARY_PROMPT_ZH,
    retries=1,
)


class CommunityIndexOp:
    """Run Leiden community detection on the entity graph and generate L2 summaries.

    Steps:
      1. Load DocTriple records for the space (optionally scoped to a document).
      2. Skip if fewer than MIN_TRIPLES.
      3. Build igraph entity graph + run multi-resolution Leiden.
      4. Atomically replace existing DocCommunity / DocCommunityTriple / DocCommunitySummary.
      5. Persist DocCommunity rows for all levels.
      6. Assign level-0 triples to communities via DocCommunityTriple.
      7. Generate LLM summaries for level-2 (coarse) communities.
      8. Index summaries to Qdrant (best-effort, never raises).
    """

    @property
    def name(self) -> str:
        return "community_index"

    @property
    def input_keys(self) -> tuple[str, ...]:
        return ("space_id", "db")

    @property
    def output_keys(self) -> tuple[str, ...]:
        return ("community_count", "summary_count")

    async def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        space_id: str = ctx["space_id"]
        db: AsyncSession = ctx["db"]
        document_id: str | None = ctx.get("document_id")

        # ── 1. Load triples ──────────────────────────────────────────────────
        stmt = select(DocTriple).where(
            DocTriple.space_id == space_id,
            DocTriple.deleted_at == None,  # noqa: E711
        )
        if document_id:
            stmt = stmt.where(DocTriple.document_id == document_id)

        result = await db.execute(stmt)
        triples_orm = result.scalars().all()

        logger.info(
            "CommunityIndexOp: loaded %d triples (space=%s, doc=%s)",
            len(triples_orm),
            space_id,
            document_id or "all",
        )

        # ── 2. Guard: too few triples ────────────────────────────────────────
        if len(triples_orm) < MIN_TRIPLES:
            ctx["community_count"] = 0
            ctx["summary_count"] = 0
            logger.info(
                "CommunityIndexOp: skipped — only %d triples (min=%d)",
                len(triples_orm),
                MIN_TRIPLES,
            )
            return ctx

        # ── Convert to plain dicts for kg_ops ───────────────────────────────
        triples = [
            {
                "subject": t.subject,
                "predicate": t.predicate,
                "object": t.object,
                "id": t.id,
                "chunk_id": t.chunk_id,
            }
            for t in triples_orm
        ]

        # ── 3. Build graph + run Leiden ──────────────────────────────────────
        graph, entity_to_idx = build_entity_graph(triples)
        idx_to_entity: dict[int, str] = {v: k for k, v in entity_to_idx.items()}

        communities_by_level = run_leiden(graph)
        # communities_by_level: {level: [[vertex_id, ...], ...]}

        # ── 4. Atomic replace: delete in FK order ────────────────────────────
        await db.execute(
            delete(DocCommunitySummary).where(DocCommunitySummary.space_id == space_id)
        )
        await db.execute(
            delete(DocCommunityTriple).where(DocCommunityTriple.space_id == space_id)
        )
        await db.execute(
            delete(DocCommunity).where(DocCommunity.space_id == space_id)
        )
        await db.flush()

        # ── 5. Persist DocCommunity for all levels ───────────────────────────
        all_communities: list[DocCommunity] = []

        for level, community_lists in communities_by_level.items():
            for i, vertex_ids in enumerate(community_lists):
                entity_names = [
                    idx_to_entity[vid]
                    for vid in vertex_ids
                    if vid in idx_to_entity
                ]
                community = DocCommunity(
                    id=uuid7().hex,
                    space_id=space_id,
                    name=f"community-L{level}-{i}",
                    resolution_level=level,
                    size=len(vertex_ids),
                    entity_ids=entity_names[:50],
                    top_entities=entity_names[:10],
                    created_by="system",
                )
                db.add(community)
                all_communities.append(community)

        await db.flush()

        community_count = len(all_communities)
        logger.info(
            "CommunityIndexOp: persisted %d communities across %d levels",
            community_count,
            len(communities_by_level),
        )

        # ── 6. Assign triples to level-0 communities (DocCommunityTriple) ────
        if 0 in communities_by_level:
            level0_lists = communities_by_level[0]

            # Build vertex_idx → community_idx for level 0
            entity_to_community: dict[int, int] = {}
            for ci, vertex_ids in enumerate(level0_lists):
                for vid in vertex_ids:
                    entity_to_community[vid] = ci

            community_triples = assign_triples_to_communities(
                triples, entity_to_idx, entity_to_community
            )
            # community_triples: {community_idx: [triple_dicts]}

            level0_db = [c for c in all_communities if c.resolution_level == 0]

            for ci, triple_list in community_triples.items():
                if ci >= len(level0_db):
                    continue
                community_obj = level0_db[ci]
                for t in triple_list:
                    ct = DocCommunityTriple(
                        id=uuid7().hex,
                        space_id=space_id,
                        community_id=community_obj.id,
                        triple_id=t["id"],
                        created_by="system",
                    )
                    db.add(ct)

            await db.flush()

        # ── 7. LLM summaries for level-2 (coarse) communities ───────────────
        level2_communities = [c for c in all_communities if c.resolution_level == 2]
        summary_count = 0
        model = make_model(SUMMARY_MODEL)

        for community in level2_communities:
            community_entity_names = set(community.entity_ids or [])
            related_triples = [
                t
                for t in triples
                if t["subject"] in community_entity_names
                or t["object"] in community_entity_names
            ]

            if not related_triples:
                continue

            triples_text = build_triple_text(related_triples, max_triples=40)

            summary_text = f"Community of {len(community_entity_names)} entities"
            key_findings: list[str] = list(community.top_entities or [])[:5]

            try:
                result = await _community_agent.run(
                    triples_text,
                    model=model,
                    model_settings={"temperature": 0.3, "max_tokens": 512},
                )
                summary_text = result.output.summary
                key_findings = result.output.key_findings

            except Exception:
                logger.warning(
                    "CommunityIndexOp: LLM summary failed for community %s, using fallback",
                    community.id,
                    exc_info=True,
                )

            doc_summary = DocCommunitySummary(
                id=uuid7().hex,
                space_id=space_id,
                community_id=community.id,
                summary=summary_text,
                key_findings=key_findings,
                representative_triples=[
                    build_triple_text([t], max_triples=1)
                    for t in related_triples[:3]
                ],
                evidence_count=len(related_triples),
                llm_model=SUMMARY_MODEL,
                created_by="system",
            )
            db.add(doc_summary)
            community.summary = summary_text
            summary_count += 1

        await db.flush()

        logger.info(
            "CommunityIndexOp: generated %d summaries for %d level-2 communities",
            summary_count,
            len(level2_communities),
        )

        # ── 8. Index summaries to Qdrant (best-effort) ──────────────────────
        try:
            from src.shared.qdrant_search import index_documents_batch
            from src.shared.search_types import IndexDocument

            index_docs: list[IndexDocument] = []
            for community in level2_communities:
                if community.summary:
                    index_docs.append(
                        IndexDocument(
                            entity_id=community.id,
                            content=community.summary,
                            metadata={
                                "resolution_level": community.resolution_level,
                                "size": community.size,
                                "name": community.name,
                            },
                            service_id=COMMUNITY_SERVICE_ID,
                            space_id=space_id,
                        )
                    )
            if index_docs:
                await index_documents_batch(index_docs)
                logger.info(
                    "CommunityIndexOp: indexed %d community summaries to Qdrant",
                    len(index_docs),
                )
        except Exception:
            logger.exception("CommunityIndexOp: Qdrant indexing failed (non-fatal)")

        ctx["community_count"] = community_count
        ctx["summary_count"] = summary_count
        return ctx

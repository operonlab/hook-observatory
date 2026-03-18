"""Catalog REST API — skill metadata, graph, and sync endpoints."""

from __future__ import annotations

import logging
from typing import Any

from db import Skill, SkillEdge, get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from services.catalog_sync import sync_catalog_to_db
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("anvil.catalog")

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CatalogSkillItem(BaseModel):
    name: str
    version: str | None
    domain: str
    description: str | None
    tags: list[Any]
    strengths: list[Any]
    pain_point: str | None
    triggers: list[Any]
    tools: list[Any]
    body_lines: int
    resources: dict[str, Any]
    io_schema: dict[str, Any] | None
    health_score: float | None
    status: str

    model_config = {"from_attributes": True}


class CatalogSkillDetail(CatalogSkillItem):
    guide: str | None
    health_details: dict[str, Any] | None
    edges: list[dict[str, Any]]


class CatalogListResponse(BaseModel):
    items: list[CatalogSkillItem]
    total: int
    limit: int
    offset: int
    domain_counts: dict[str, int]


class EdgeItem(BaseModel):
    source: str
    target: str
    type: str
    strength: float
    description: str | None

    model_config = {"from_attributes": True, "populate_by_name": True}

    @classmethod
    def from_db(cls, e: Any) -> EdgeItem:
        return cls(
            source=e.source,
            target=e.target,
            type=e.edge_type,
            strength=e.strength,
            description=e.description,
        )


class GraphNode(BaseModel):
    id: str
    domain: str
    description: str | None
    health_score: float | None
    val: int  # visual weight based on edge count


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[EdgeItem]
    stats: dict[str, Any]


class SyncResponse(BaseModel):
    synced_skills: int
    edges: int
    errors: list[str]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/catalog/skills")
async def list_catalog_skills(
    q: str | None = Query(None, description="Search in name, description, pain_point"),
    domain: str | None = Query(None, description="Exact domain filter"),
    sort: str = Query("name", description="Sort field: name|health_score|domain"),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> CatalogListResponse:
    """List skills with optional full-text search and domain filter."""
    query = select(Skill)
    count_query = select(func.count()).select_from(Skill)

    if q:
        like_expr = f"%{q}%"
        search_filter = or_(
            Skill.name.ilike(like_expr),
            Skill.description.ilike(like_expr),
            Skill.pain_point.ilike(like_expr),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    if domain:
        query = query.where(Skill.domain == domain)
        count_query = count_query.where(Skill.domain == domain)

    # Sort
    sort_col = {
        "name": Skill.name,
        "health_score": Skill.health_score.desc().nulls_last(),
        "domain": Skill.domain,
    }.get(sort, Skill.name)
    query = query.order_by(sort_col)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(query.offset(offset).limit(limit))
    skills = result.scalars().all()

    # Domain counts (across full unfiltered set for sidebar use)
    domain_result = await db.execute(
        select(Skill.domain, func.count().label("cnt"))
        .group_by(Skill.domain)
        .order_by(Skill.domain)
    )
    domain_counts = {row[0]: row[1] for row in domain_result.all()}

    items = [CatalogSkillItem.model_validate(s) for s in skills]
    return CatalogListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        domain_counts=domain_counts,
    )


@router.get("/catalog/skills/{name}")
async def get_catalog_skill(
    name: str,
    db: AsyncSession = Depends(get_session),
) -> CatalogSkillDetail:
    """Get full skill detail including guide, health_details, and connected edges."""
    result = await db.execute(select(Skill).where(Skill.name == name))
    skill = result.scalar_one_or_none()
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found in catalog")

    # Connected edges (source OR target)
    edges_result = await db.execute(
        select(SkillEdge).where(or_(SkillEdge.source == name, SkillEdge.target == name))
    )
    edge_objs = edges_result.scalars().all()
    edges = [
        {
            "source": e.source,
            "target": e.target,
            "type": e.edge_type,
            "strength": e.strength,
            "description": e.description,
        }
        for e in edge_objs
    ]

    base = CatalogSkillItem.model_validate(skill).model_dump()
    return CatalogSkillDetail(
        **base,
        guide=skill.guide,
        health_details=skill.health_details,
        edges=edges,
    )


@router.get("/catalog/graph")
async def get_skill_graph(
    db: AsyncSession = Depends(get_session),
) -> GraphResponse:
    """Return full skill graph (nodes + edges) for 3D visualisation."""
    # Fetch all skills
    skills_result = await db.execute(select(Skill))
    skills = skills_result.scalars().all()

    # Fetch all edges
    edges_result = await db.execute(select(SkillEdge))
    edges = edges_result.scalars().all()

    # Compute per-node edge count for visual weight
    edge_count: dict[str, int] = {}
    for e in edges:
        edge_count[e.source] = edge_count.get(e.source, 0) + 1
        edge_count[e.target] = edge_count.get(e.target, 0) + 1

    nodes = [
        GraphNode(
            id=s.name,
            domain=s.domain,
            description=s.pain_point or s.description,
            health_score=s.health_score,
            val=max(2, min(12, 2 + edge_count.get(s.name, 0) // 2)),
        )
        for s in skills
    ]

    # Domain distribution
    domain_dist: dict[str, int] = {}
    for s in skills:
        domain_dist[s.domain] = domain_dist.get(s.domain, 0) + 1

    stats = {
        "total_skills": len(skills),
        "total_edges": len(edges),
        "domain_distribution": dict(sorted(domain_dist.items(), key=lambda x: -x[1])),
    }

    return GraphResponse(
        nodes=nodes,
        edges=[EdgeItem.from_db(e) for e in edges],
        stats=stats,
    )


@router.post("/catalog/sync")
async def sync_catalog(
    db: AsyncSession = Depends(get_session),
) -> SyncResponse:
    """Sync skill catalog from filesystem into the database."""
    result = await sync_catalog_to_db(db)
    return SyncResponse(**result)

"""Nodeflow routes — REST API endpoints.

Prefix: /api/nodeflow (mounted in main.py)
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.errors import NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from .schemas import (
    EdgeCreate,
    EdgeResponse,
    FlowCreate,
    FlowDetailResponse,
    FlowResponse,
    FlowRunDetailResponse,
    FlowRunResponse,
    FlowUpdate,
    NodeCreate,
    NodeResponse,
    NodeUpdate,
)
from .services import (
    edge_service,
    flow_run_service,
    flow_service,
    node_service,
)

router = APIRouter(tags=["nodeflow"])


# ======================== Flows ========================


@router.get("/flows", response_model=PaginatedResponse[FlowResponse])
async def list_flows(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.read"),
):
    return await flow_service.list(
        db, space_id, PaginationParams(page=page, page_size=page_size)
    )


@router.get("/flows/{flow_id}", response_model=FlowDetailResponse)
async def get_flow(
    flow_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.read"),
):
    return await flow_service.get_detail(db, flow_id)


@router.post("/flows", response_model=FlowResponse, status_code=201)
async def create_flow(
    data: FlowCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.write"),
):
    instance = await flow_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return flow_service.to_response(instance)


@router.put("/flows/{flow_id}", response_model=FlowResponse)
async def update_flow(
    flow_id: str,
    data: FlowUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.write"),
):
    instance = await flow_service.update(db, flow_id, data, user_id=user.get("id"))
    if not instance:
        raise NotFoundError("Flow not found", code="nodeflow.flow_not_found")
    await db.commit()
    return flow_service.to_response(instance)


@router.post("/flows/{flow_id}/activate", response_model=FlowResponse)
async def activate_flow(
    flow_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.write"),
):
    result = await flow_service.activate(db, flow_id)
    await db.commit()
    return result


@router.post("/flows/{flow_id}/pause", response_model=FlowResponse)
async def pause_flow(
    flow_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.write"),
):
    result = await flow_service.pause(db, flow_id)
    await db.commit()
    return result


class ManualTriggerRequest(BaseModel):
    input_data: dict[str, Any] | None = None


@router.post("/flows/{flow_id}/trigger", response_model=FlowRunResponse)
async def trigger_flow(
    flow_id: str,
    body: ManualTriggerRequest | None = None,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.write"),
):
    result = await flow_service.trigger_manual(
        db,
        flow_id,
        space_id,
        user_id=user.get("id"),
        input_data=body.input_data if body else None,
    )
    await db.commit()
    return result


# ======================== Nodes ========================


@router.get("/flows/{flow_id}/nodes", response_model=list[NodeResponse])
async def list_nodes(
    flow_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.read"),
):
    from sqlalchemy import select

    from .models import Node

    q = select(Node).where(Node.flow_id == flow_id, Node.deleted_at == None)  # noqa: E711
    rows = (await db.execute(q)).scalars().all()
    return [node_service.to_response(n) for n in rows]


@router.post("/nodes", response_model=NodeResponse, status_code=201)
async def create_node(
    data: NodeCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.write"),
):
    instance = await node_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return node_service.to_response(instance)


@router.put("/nodes/{node_id}", response_model=NodeResponse)
async def update_node(
    node_id: str,
    data: NodeUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.write"),
):
    instance = await node_service.update(db, node_id, data, user_id=user.get("id"))
    if not instance:
        raise NotFoundError("Node not found", code="nodeflow.node_not_found")
    await db.commit()
    return node_service.to_response(instance)


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(
    node_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.write"),
):
    await node_service.soft_delete(db, node_id, user_id=user.get("id"))
    await db.commit()


# ======================== Edges ========================


@router.get("/flows/{flow_id}/edges", response_model=list[EdgeResponse])
async def list_edges(
    flow_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.read"),
):
    return await edge_service.list_by_flow(db, flow_id)


@router.post("/edges", response_model=EdgeResponse, status_code=201)
async def create_edge(
    data: EdgeCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.write"),
):
    instance = await edge_service.create(db, space_id, data, user_id=user.get("id"))
    await db.commit()
    return edge_service.to_response(instance)


@router.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(
    edge_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.write"),
):
    await edge_service.delete(db, edge_id)
    await db.commit()


# ======================== Flow Runs ========================


@router.get("/flows/{flow_id}/runs", response_model=PaginatedResponse[FlowRunResponse])
async def list_flow_runs(
    flow_id: str,
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.read"),
):
    return await flow_run_service.list_by_flow(
        db, flow_id, space_id, PaginationParams(page=page, page_size=page_size)
    )


@router.get("/flow-runs/{flow_run_id}", response_model=FlowRunDetailResponse)
async def get_flow_run(
    flow_run_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = require_permission("nodeflow.read"),
):
    return await flow_run_service.get_detail(db, flow_run_id)


# ======================== Registry ========================


@router.get("/actions")
async def list_available_actions(
    user: dict = require_permission("nodeflow.read"),
):
    from .registry import list_actions

    return {"actions": list_actions()}

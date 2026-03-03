"""Nodeflow services — CRUD for flows + DAG execution.

This is the PUBLIC API of the nodeflow module.
"""

import asyncio
from collections.abc import Sequence
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.events.bus import Event, event_bus
from src.events.types import NodeflowEvents
from src.shared.errors import BadRequestError, NotFoundError
from src.shared.models import _uuid7_hex
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService

from .engine import execute_flow
from .models import Edge, Flow, FlowRun, Node
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
    NodeRunLogResponse,
    NodeUpdate,
)

logger = structlog.get_logger()


def _soft_delete_filter(q, model):
    return q.where(model.deleted_at == None)  # noqa: E711


# ======================== Flow Service ========================


class FlowService(BaseCRUDService[Flow, FlowCreate, FlowUpdate, FlowResponse]):
    model = Flow
    audit_module = "nodeflow"
    audit_entity_type = "flows"

    def to_response(self, instance: Flow) -> FlowResponse:
        return FlowResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            name=instance.name,
            description=instance.description,
            trigger_type=instance.trigger_type,
            trigger_config=instance.trigger_config,
            status=instance.status,
            deleted_at=instance.deleted_at,
        )

    def to_detail_response(self, instance: Flow) -> FlowDetailResponse:
        return FlowDetailResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            name=instance.name,
            description=instance.description,
            trigger_type=instance.trigger_type,
            trigger_config=instance.trigger_config,
            status=instance.status,
            deleted_at=instance.deleted_at,
            nodes=[node_service.to_response(n) for n in instance.nodes if n.deleted_at is None],
            edges=[edge_service.to_response(e) for e in instance.edges if e.deleted_at is None],
        )

    async def get_detail(self, db: AsyncSession, flow_id: str) -> FlowDetailResponse:
        q = (
            select(Flow)
            .where(Flow.id == flow_id)
            .options(selectinload(Flow.nodes), selectinload(Flow.edges))
        )
        result = await db.execute(q)
        flow = result.scalar_one_or_none()
        if not flow or flow.deleted_at is not None:
            raise NotFoundError("Flow not found", code="nodeflow.flow_not_found")
        return self.to_detail_response(flow)

    async def activate(self, db: AsyncSession, flow_id: str) -> FlowResponse:
        flow = await db.get(Flow, flow_id)
        if not flow or flow.deleted_at is not None:
            raise NotFoundError("Flow not found", code="nodeflow.flow_not_found")
        if flow.status == "active":
            return self.to_response(flow)
        flow.status = "active"
        await db.flush()
        await event_bus.publish(Event(
            type=NodeflowEvents.FLOW_ACTIVATED,
            data={"flow_id": flow.id, "name": flow.name},
            source="nodeflow",
        ))
        return self.to_response(flow)

    async def pause(self, db: AsyncSession, flow_id: str) -> FlowResponse:
        flow = await db.get(Flow, flow_id)
        if not flow or flow.deleted_at is not None:
            raise NotFoundError("Flow not found", code="nodeflow.flow_not_found")
        flow.status = "paused"
        await db.flush()
        await event_bus.publish(Event(
            type=NodeflowEvents.FLOW_PAUSED,
            data={"flow_id": flow.id, "name": flow.name},
            source="nodeflow",
        ))
        return self.to_response(flow)

    async def trigger_manual(
        self,
        db: AsyncSession,
        flow_id: str,
        space_id: str,
        user_id: str | None = None,
        input_data: dict[str, Any] | None = None,
    ) -> FlowRunResponse:
        """Manually trigger a flow execution."""
        q = (
            select(Flow)
            .where(Flow.id == flow_id, Flow.space_id == space_id)
            .options(selectinload(Flow.nodes), selectinload(Flow.edges))
        )
        result = await db.execute(q)
        flow = result.scalar_one_or_none()
        if not flow or flow.deleted_at is not None:
            raise NotFoundError("Flow not found", code="nodeflow.flow_not_found")
        if flow.status not in ("active", "draft"):
            raise BadRequestError(
                "Flow must be active or draft to trigger",
                code="nodeflow.flow_not_triggerable",
            )

        trigger_data = input_data or {}
        flow_run = await execute_flow(db, flow, trigger_data, user_id=user_id)
        return flow_run_service.to_response(flow_run)


# ======================== Node Service ========================


class NodeService(BaseCRUDService[Node, NodeCreate, NodeUpdate, NodeResponse]):
    model = Node
    audit_module = "nodeflow"
    audit_entity_type = "nodes"

    def to_response(self, instance: Node) -> NodeResponse:
        return NodeResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            flow_id=instance.flow_id,
            node_type=instance.node_type,
            label=instance.label,
            config=instance.config,
            position_x=instance.position_x,
            position_y=instance.position_y,
            deleted_at=instance.deleted_at,
        )


# ======================== Edge Service ========================


class EdgeService:
    """Edge CRUD — not using BaseCRUDService since edges are simpler."""

    def to_response(self, instance: Edge) -> EdgeResponse:
        return EdgeResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            flow_id=instance.flow_id,
            source_node_id=instance.source_node_id,
            target_node_id=instance.target_node_id,
            source_port=instance.source_port,
            deleted_at=instance.deleted_at,
        )

    async def create(
        self, db: AsyncSession, space_id: str, data: EdgeCreate, user_id: str | None = None
    ) -> Edge:
        edge = Edge(
            id=_uuid7_hex(),
            space_id=space_id,
            created_by=user_id or "",
            flow_id=data.flow_id,
            source_node_id=data.source_node_id,
            target_node_id=data.target_node_id,
            source_port=data.source_port,
        )
        db.add(edge)
        await db.flush()
        await db.refresh(edge)
        return edge

    async def delete(self, db: AsyncSession, edge_id: str) -> None:
        edge = await db.get(Edge, edge_id)
        if edge:
            await db.delete(edge)
            await db.flush()

    async def list_by_flow(
        self, db: AsyncSession, flow_id: str
    ) -> list[EdgeResponse]:
        q = select(Edge).where(Edge.flow_id == flow_id)
        q = _soft_delete_filter(q, Edge)
        rows: Sequence[Edge] = (await db.execute(q)).scalars().all()
        return [self.to_response(e) for e in rows]


# ======================== FlowRun Service ========================


class FlowRunService:
    def to_response(self, instance: FlowRun) -> FlowRunResponse:
        return FlowRunResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            flow_id=instance.flow_id,
            status=instance.status,
            trigger_event=instance.trigger_event,
            started_at=instance.started_at,
            finished_at=instance.finished_at,
            error=instance.error,
            deleted_at=instance.deleted_at,
        )

    def to_detail_response(self, instance: FlowRun) -> FlowRunDetailResponse:
        return FlowRunDetailResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            flow_id=instance.flow_id,
            status=instance.status,
            trigger_event=instance.trigger_event,
            started_at=instance.started_at,
            finished_at=instance.finished_at,
            error=instance.error,
            deleted_at=instance.deleted_at,
            node_run_logs=[
                NodeRunLogResponse(
                    id=log.id,
                    space_id=log.space_id,
                    created_by=log.created_by,
                    created_at=log.created_at,
                    updated_at=log.updated_at,
                    flow_run_id=log.flow_run_id,
                    node_id=log.node_id,
                    status=log.status,
                    input_data=log.input_data,
                    output_data=log.output_data,
                    error=log.error,
                    started_at=log.started_at,
                    finished_at=log.finished_at,
                    deleted_at=log.deleted_at,
                )
                for log in instance.node_run_logs
            ],
        )

    async def list_by_flow(
        self,
        db: AsyncSession,
        flow_id: str,
        space_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[FlowRunResponse]:
        p = pagination or PaginationParams()
        base = select(FlowRun).where(
            FlowRun.flow_id == flow_id,
            FlowRun.space_id == space_id,
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()

        q = (
            base.order_by(FlowRun.started_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows: Sequence[FlowRun] = (await db.execute(q)).scalars().all()
        return PaginatedResponse[FlowRunResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def get_detail(
        self, db: AsyncSession, flow_run_id: str
    ) -> FlowRunDetailResponse:
        q = (
            select(FlowRun)
            .where(FlowRun.id == flow_run_id)
            .options(selectinload(FlowRun.node_run_logs))
        )
        result = await db.execute(q)
        run = result.scalar_one_or_none()
        if not run:
            raise NotFoundError("Flow run not found", code="nodeflow.flow_run_not_found")
        return self.to_detail_response(run)


# ======================== Event-Driven Execution ========================


_background_tasks: set[asyncio.Task] = set()  # prevent GC of fire-and-forget tasks


async def on_any_event(event: Event) -> None:
    """Wildcard event handler — check if any active flow should be triggered.

    Registered via event_bus.subscribe("*", on_any_event) at startup.
    """
    from src.shared.database import async_session_factory

    # Skip nodeflow's own events to prevent infinite loops
    if event.type.startswith("nodeflow."):
        return

    async with async_session_factory() as db:
        try:
            q = (
                select(Flow)
                .where(
                    Flow.status == "active",
                    Flow.trigger_type == "event",
                    Flow.deleted_at == None,  # noqa: E711
                )
                .options(selectinload(Flow.nodes), selectinload(Flow.edges))
            )
            flows: Sequence[Flow] = (await db.execute(q)).scalars().all()

            for flow in flows:
                config = flow.trigger_config or {}
                target_event = config.get("event_type", "")
                if target_event and target_event == event.type:
                    logger.info(
                        "nodeflow_event_trigger",
                        flow_id=flow.id,
                        flow_name=flow.name,
                        event_type=event.type,
                    )
                    task = asyncio.create_task(
                        _execute_in_session(flow.id, flow.space_id, event)
                    )
                    _background_tasks.add(task)
                    task.add_done_callback(_background_tasks.discard)

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("nodeflow_event_match_failed", event_type=event.type)


async def _execute_in_session(flow_id: str, space_id: str, event: Event) -> None:
    """Execute a flow in its own DB session (for fire-and-forget tasks)."""
    from src.shared.database import async_session_factory

    async with async_session_factory() as db:
        try:
            q = (
                select(Flow)
                .where(Flow.id == flow_id)
                .options(selectinload(Flow.nodes), selectinload(Flow.edges))
            )
            flow = (await db.execute(q)).scalar_one_or_none()
            if flow:
                await execute_flow(db, flow, event.data, user_id=event.user_id)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("nodeflow_execution_failed", flow_id=flow_id)


# ======================== Global Instances ========================

flow_service = FlowService()
node_service = NodeService()
edge_service = EdgeService()
flow_run_service = FlowRunService()

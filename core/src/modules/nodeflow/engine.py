"""DAG execution engine — topological sort → sequential node execution."""

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.events.types import NodeflowEvents
from src.shared.fsm import validate_transition
from src.shared.models import _uuid7_hex

from .executors import EXECUTOR_MAP
from .executors.base import ExecutionContext, ExecutionResult
from .lifecycle import FlowRunLifecycle, NodeRunLifecycle
from .models import Edge, Flow, FlowRun, Node, NodeRunLog
from .store import StateTransitioned, nodeflow_store

logger = structlog.get_logger()


async def execute_flow(
    db: AsyncSession,
    flow: Flow,
    trigger_data: dict[str, Any],
    user_id: str | None = None,
) -> FlowRun:
    """Execute a flow's DAG given trigger data.

    1. Create FlowRun record
    2. Topological sort nodes
    3. Execute each node in order, passing data along edges
    4. Record NodeRunLog for each step
    """
    # Create flow run
    flow_run = FlowRun(
        id=_uuid7_hex(),
        space_id=flow.space_id,
        created_by=user_id or flow.created_by,
        flow_id=flow.id,
        status="running",
        trigger_event=trigger_data,
        started_at=datetime.now(UTC),
    )
    db.add(flow_run)
    await db.flush()

    await event_bus.publish(
        Event(
            type=NodeflowEvents.FLOW_RUN_STARTED,
            data={"flow_id": flow.id, "flow_run_id": flow_run.id, "flow_name": flow.name},
            source="nodeflow",
            user_id=user_id,
        )
    )

    try:
        # Build adjacency from edges
        nodes_by_id = {n.id: n for n in flow.nodes if n.deleted_at is None}
        edges = [e for e in flow.edges if e.deleted_at is None]

        sorted_nodes = _topological_sort(nodes_by_id, edges)

        # Track output data per node for edge-based data passing
        node_outputs: dict[str, ExecutionResult] = {}

        for node in sorted_nodes:
            executor_cls = EXECUTOR_MAP.get(node.node_type)
            if not executor_cls:
                logger.warning("nodeflow_unknown_node_type", node_type=node.node_type)
                continue

            # Gather input: merge outputs from upstream nodes
            input_data = _gather_input(node.id, edges, node_outputs, trigger_data)

            # Create log entry
            node_log = NodeRunLog(
                id=_uuid7_hex(),
                space_id=flow.space_id,
                created_by=user_id or flow.created_by,
                flow_run_id=flow_run.id,
                node_id=node.id,
                status="running",
                input_data=input_data,
                started_at=datetime.now(UTC),
            )
            db.add(node_log)
            await db.flush()

            try:
                ctx = ExecutionContext(
                    db=db,
                    space_id=flow.space_id,
                    user_id=user_id,
                    flow_run_id=flow_run.id,
                    input_data=input_data,
                )
                result = await executor_cls().execute(node.config or {}, ctx)
                node_outputs[node.id] = result

                validate_transition(NodeRunLifecycle, node_log.status, "completed", "NodeRun")
                node_log.status = "completed"
                node_log.output_data = result.data
                node_log.finished_at = datetime.now(UTC)

            except Exception as exc:
                validate_transition(NodeRunLifecycle, node_log.status, "failed", "NodeRun")
                node_log.status = "failed"
                node_log.error = str(exc)
                node_log.finished_at = datetime.now(UTC)
                logger.exception(
                    "nodeflow_node_failed",
                    node_id=node.id,
                    node_type=node.node_type,
                )
                # Fail the entire run on node failure
                raise

            await db.flush()

        # Mark skipped nodes (downstream of false condition branches)
        _mark_skipped_nodes(nodes_by_id, edges, node_outputs, flow_run, flow.space_id, user_id, db)

        validate_transition(FlowRunLifecycle, flow_run.status, "completed", "FlowRun")
        flow_run.status = "completed"
        flow_run.finished_at = datetime.now(UTC)
        await nodeflow_store.dispatch(
            StateTransitioned(
                module="nodeflow",
                entity_type="flow_run",
                entity_id=str(flow_run.id),
                old_state="running",
                new_state="completed",
                user_id=user_id,
            )
        )

        await event_bus.publish(
            Event(
                type=NodeflowEvents.FLOW_RUN_COMPLETED,
                data={"flow_id": flow.id, "flow_run_id": flow_run.id},
                source="nodeflow",
                user_id=user_id,
            )
        )

    except Exception as exc:
        validate_transition(FlowRunLifecycle, flow_run.status, "failed", "FlowRun")
        flow_run.status = "failed"
        flow_run.error = str(exc)
        flow_run.finished_at = datetime.now(UTC)
        await nodeflow_store.dispatch(
            StateTransitioned(
                module="nodeflow",
                entity_type="flow_run",
                entity_id=str(flow_run.id),
                old_state="running",
                new_state="failed",
                user_id=user_id,
            )
        )

        try:
            await event_bus.publish(
                Event(
                    type=NodeflowEvents.FLOW_RUN_FAILED,
                    data={"flow_id": flow.id, "flow_run_id": flow_run.id, "error": str(exc)},
                    source="nodeflow",
                    user_id=user_id,
                )
            )
        except Exception:
            logger.warning("Failed to publish FLOW_RUN_FAILED event", exc_info=True)

    await db.flush()
    return flow_run


def _topological_sort(nodes: dict[str, Node], edges: list[Edge]) -> list[Node]:
    """Kahn's algorithm for topological ordering."""
    in_degree: dict[str, int] = defaultdict(int)
    adj: dict[str, list[str]] = defaultdict(list)

    for nid in nodes:
        in_degree.setdefault(nid, 0)

    for e in edges:
        if e.source_node_id in nodes and e.target_node_id in nodes:
            adj[e.source_node_id].append(e.target_node_id)
            in_degree[e.target_node_id] += 1

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    result: list[Node] = []

    while queue:
        nid = queue.pop(0)
        if nid in nodes:
            result.append(nodes[nid])
        for neighbor in adj.get(nid, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return result


def _gather_input(
    node_id: str,
    edges: list[Edge],
    node_outputs: dict[str, ExecutionResult],
    trigger_data: dict[str, Any],
) -> dict[str, Any]:
    """Merge output data from all upstream nodes connected to this node."""
    incoming = [e for e in edges if e.target_node_id == node_id]
    if not incoming:
        return dict(trigger_data)

    merged: dict[str, Any] = {}
    for edge in incoming:
        upstream_result = node_outputs.get(edge.source_node_id)
        if upstream_result is None:
            continue
        # Only pass data if the edge's source_port matches the result's output_port
        if edge.source_port == upstream_result.output_port:
            merged.update(upstream_result.data)

    return merged or dict(trigger_data)


def _mark_skipped_nodes(
    nodes: dict[str, Node],
    edges: list[Edge],
    node_outputs: dict[str, ExecutionResult],
    flow_run: FlowRun,
    space_id: str,
    user_id: str | None,
    db: AsyncSession,
) -> None:
    """Mark nodes that were not executed (unreachable branches) as skipped."""
    executed = set(node_outputs.keys())
    for nid, _node in nodes.items():
        if nid not in executed:
            log = NodeRunLog(
                id=_uuid7_hex(),
                space_id=space_id,
                created_by=user_id or flow_run.created_by,
                flow_run_id=flow_run.id,
                node_id=nid,
                status="skipped",
            )
            db.add(log)

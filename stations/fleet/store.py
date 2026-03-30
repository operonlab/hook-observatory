"""Fleet Station — NgRx-style FeatureStore (node state + task dispatch).

Reducer + Selector depth: tracks tasks and nodes in immutable state.
Mirrors the runtime state held by TaskStore/NodeRegistry, providing
a reactive projection layer for monitoring and derived queries.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import update_in
from src.shared.middleware import PerformanceMiddleware
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect, register_effects

logger = logging.getLogger(__name__)

# ── Actions ──────────────────────────────────────────────────────────────

TaskDispatched = create_action("fleet.task.dispatched")
TaskRunning = create_action("fleet.task.running")
TaskCompleted = create_action("fleet.task.completed")
TaskFailed = create_action("fleet.task.failed")
TaskCancelled = create_action("fleet.task.cancelled")

NodeRegistered = create_action("fleet.node.registered")
NodeHealthUpdated = create_action("fleet.node.health_updated")
NodeOffline = create_action("fleet.node.offline")

# ── Reducer ──────────────────────────────────────────────────────────────

_INITIAL_STATE = {
    "tasks": {},
    "nodes": {},
    "active_count": 0,
}


def _p(action):
    """Safe payload accessor — returns empty dict if payload is None."""
    return action.payload or {}


fleet_reducer = create_reducer(
    _INITIAL_STATE,
    # Task lifecycle
    on(
        TaskDispatched,
        lambda s, a: update_in(
            s,
            ["tasks", _p(a).get("task_id", "")],
            lambda _: {**_p(a), "status": "dispatched"},
        ),
    ),
    on(
        TaskRunning,
        lambda s, a: update_in(
            s,
            ["tasks", _p(a).get("task_id", ""), "status"],
            lambda _: "running",
        ),
    ),
    on(
        TaskCompleted,
        lambda s, a: update_in(
            s,
            ["tasks", _p(a).get("task_id", ""), "status"],
            lambda _: "completed",
        ),
    ),
    on(
        TaskFailed,
        lambda s, a: update_in(
            s,
            ["tasks", _p(a).get("task_id", ""), "status"],
            lambda _: "failed",
        ),
    ),
    on(
        TaskCancelled,
        lambda s, a: update_in(
            s,
            ["tasks", _p(a).get("task_id", ""), "status"],
            lambda _: "cancelled",
        ),
    ),
    # Node lifecycle
    on(
        NodeRegistered,
        lambda s, a: update_in(
            s,
            ["nodes", _p(a).get("node_id", "")],
            lambda _: {**_p(a), "healthy": False},
        ),
    ),
    on(
        NodeHealthUpdated,
        lambda s, a: update_in(
            s,
            ["nodes", _p(a).get("node_id", "")],
            lambda prev: {**(prev or {}), **_p(a)},
        ),
    ),
    on(
        NodeOffline,
        lambda s, a: update_in(
            s,
            ["nodes", _p(a).get("node_id", ""), "healthy"],
            lambda _: False,
        ),
    ),
)

# ── Selectors ─────────────────────────────────────────────────────────────

select_tasks = create_selector(lambda s: s["tasks"])
select_nodes = create_selector(lambda s: s["nodes"])

select_active_tasks = create_selector(
    select_tasks,
    result_fn=lambda ts: {
        k: v for k, v in ts.items() if v.get("status") in ("dispatched", "running")
    },
)

select_healthy_nodes = create_selector(
    select_nodes,
    result_fn=lambda ns: {k: v for k, v in ns.items() if v.get("healthy", False)},
)

select_failed_tasks = create_selector(
    select_tasks,
    result_fn=lambda ts: {k: v for k, v in ts.items() if v.get("status") == "failed"},
)

select_active_count = create_selector(
    select_active_tasks,
    result_fn=lambda active: len(active),
)

select_healthy_count = create_selector(
    select_healthy_nodes,
    result_fn=lambda healthy: len(healthy),
)

# ── Store Singleton ───────────────────────────────────────────────────────

fleet_store: FeatureStore = FeatureStore(
    "fleet",
    fleet_reducer,
    middlewares=[PerformanceMiddleware(warn_threshold_ms=200.0)],
)

# ── Effects ───────────────────────────────────────────────────────────────


@effect(TaskCompleted, store=fleet_store)
async def log_task_result(action, store) -> None:
    """Log task completion result (task_id, node_id, duration)."""
    p = action.payload or {}
    task_id = p.get("task_id", "unknown")
    node_id = p.get("node_id", "unknown")
    duration_ms = p.get("duration_ms")
    logger.info(
        "fleet.task_completed",
        extra={
            "task_id": task_id,
            "node_id": node_id,
            "duration_ms": duration_ms,
        },
    )


@effect(TaskFailed, store=fleet_store)
async def log_task_failure_warning(action, store) -> None:
    """Log WARNING with failure reason and retry count."""
    p = action.payload or {}
    task_id = p.get("task_id", "unknown")
    node_id = p.get("node_id", "unknown")
    error = p.get("error") or p.get("reason", "")
    retry_count = p.get("retry_count", 0)
    logger.warning(
        "fleet.task_failed",
        extra={
            "task_id": task_id,
            "node_id": node_id,
            "error": error,
            "retry_count": retry_count,
        },
    )


@effect(NodeOffline, store=fleet_store)
async def log_node_offline_alert(action, store) -> None:
    """Log node offline alert and count remaining healthy nodes."""
    p = action.payload or {}
    node_id = p.get("node_id", "unknown")

    state = store.get_state()
    nodes = state.get("nodes", {})
    # Count healthy nodes excluding the one that just went offline
    remaining_healthy = sum(
        1
        for nid, v in nodes.items()
        if nid != node_id and (v.get("healthy", False) if isinstance(v, dict) else False)
    )
    logger.warning(
        "fleet.node_offline",
        extra={
            "node_id": node_id,
            "remaining_healthy_nodes": remaining_healthy,
        },
    )


register_effects(fleet_store, log_task_result, log_task_failure_warning, log_node_offline_alert)

"""Fleet Station — NgRx-style FeatureStore (node state + task dispatch).

Reducer + Selector depth: tracks tasks and nodes in immutable state.
Mirrors the runtime state held by TaskStore/NodeRegistry, providing
a reactive projection layer for monitoring and derived queries.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import update_in
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

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

fleet_reducer = create_reducer(
    _INITIAL_STATE,
    # Task lifecycle
    on(
        TaskDispatched,
        lambda s, a: update_in(
            s,
            ["tasks", a.payload.get("task_id", "")],
            lambda _: {**a.payload, "status": "dispatched"},
        ),
    ),
    on(
        TaskRunning,
        lambda s, a: update_in(
            s,
            ["tasks", a.payload.get("task_id", ""), "status"],
            lambda _: "running",
        ),
    ),
    on(
        TaskCompleted,
        lambda s, a: update_in(
            s,
            ["tasks", a.payload.get("task_id", ""), "status"],
            lambda _: "completed",
        ),
    ),
    on(
        TaskFailed,
        lambda s, a: update_in(
            s,
            ["tasks", a.payload.get("task_id", ""), "status"],
            lambda _: "failed",
        ),
    ),
    on(
        TaskCancelled,
        lambda s, a: update_in(
            s,
            ["tasks", a.payload.get("task_id", ""), "status"],
            lambda _: "cancelled",
        ),
    ),
    # Node lifecycle
    on(
        NodeRegistered,
        lambda s, a: update_in(
            s,
            ["nodes", a.payload.get("node_id", "")],
            lambda _: {**a.payload, "healthy": False},
        ),
    ),
    on(
        NodeHealthUpdated,
        lambda s, a: update_in(
            s,
            ["nodes", a.payload.get("node_id", "")],
            lambda prev: {**(prev or {}), **a.payload},
        ),
    ),
    on(
        NodeOffline,
        lambda s, a: update_in(
            s,
            ["nodes", a.payload.get("node_id", ""), "healthy"],
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

fleet_store: FeatureStore = FeatureStore("fleet", fleet_reducer)

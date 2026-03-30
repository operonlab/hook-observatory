"""Nodeflow state management — FeatureStore for workflow orchestration."""

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import update_in
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect, register_effects

# ── Actions ──────────────────────────────────────────────────────────────

FlowCreated = create_action("nodeflow.flow.created")
FlowUpdated = create_action("nodeflow.flow.updated")
FlowActivated = create_action("nodeflow.flow.activated")
FlowPaused = create_action("nodeflow.flow.paused")
FlowArchived = create_action("nodeflow.flow.archived")
FlowRunStarted = create_action("nodeflow.flow_run.started")
FlowRunCompleted = create_action("nodeflow.flow_run.completed")
FlowRunFailed = create_action("nodeflow.flow_run.failed")
NodeExecuted = create_action("nodeflow.node.executed")
NodeFailed = create_action("nodeflow.node.failed")

# ── Reducer ──────────────────────────────────────────────────────────────

nodeflow_reducer = create_reducer(
    {
        "flows": {},
        "active_runs": {},
        "completed_runs": 0,
        "failed_runs": 0,
    },
    on(
        FlowCreated,
        lambda s, a: update_in(
            s,
            ["flows", a.payload.get("id", "") if a.payload else ""],
            lambda _: a.payload,
        ),
    ),
    on(
        FlowUpdated,
        lambda s, a: update_in(
            s,
            ["flows", a.payload.get("id", "") if a.payload else ""],
            lambda existing: {**(existing or {}), **(a.payload or {})},
        ),
    ),
    on(
        FlowActivated,
        lambda s, a: update_in(
            s,
            ["flows", a.payload.get("id", "") if a.payload else ""],
            lambda existing: {**(existing or {}), "status": "active"},
        ),
    ),
    on(
        FlowPaused,
        lambda s, a: update_in(
            s,
            ["flows", a.payload.get("id", "") if a.payload else ""],
            lambda existing: {**(existing or {}), "status": "paused"},
        ),
    ),
    on(
        FlowArchived,
        lambda s, a: update_in(
            s,
            ["flows", a.payload.get("id", "") if a.payload else ""],
            lambda existing: {**(existing or {}), "status": "archived"},
        ),
    ),
    on(
        FlowRunStarted,
        lambda s, a: update_in(
            s,
            ["active_runs", a.payload.get("run_id", "") if a.payload else ""],
            lambda _: a.payload,
        ),
    ),
    on(
        FlowRunCompleted,
        lambda s, a: s.set("completed_runs", s["completed_runs"] + 1),
    ),
    on(
        FlowRunFailed,
        lambda s, a: s.set("failed_runs", s["failed_runs"] + 1),
    ),
    on(
        NodeExecuted,
        lambda s, a: s,  # node execution is transient — no persistent state change
    ),
    on(
        NodeFailed,
        lambda s, a: s,  # node failures tracked at run level
    ),
)

# ── Store ─────────────────────────────────────────────────────────────────

nodeflow_store: FeatureStore = FeatureStore("nodeflow", nodeflow_reducer)

# ── Selectors ─────────────────────────────────────────────────────────────

select_flows = create_selector(lambda s: dict(s["flows"]) if s["flows"] else {})

select_active_flows = create_selector(
    lambda s: {k: v for k, v in s["flows"].items() if v and v.get("status") == "active"}
)

select_active_runs = create_selector(lambda s: dict(s["active_runs"]) if s["active_runs"] else {})

select_nodeflow_stats = create_selector(
    lambda s: {
        "total_flows": len(s["flows"]),
        "active_runs": len(s["active_runs"]),
        "completed_runs": s["completed_runs"],
        "failed_runs": s["failed_runs"],
    }
)

# ── Effects ───────────────────────────────────────────────────────────────


@effect(FlowRunCompleted)
async def on_flow_completed(action, store):
    """Log flow completion metrics."""
    pass  # placeholder — metrics/telemetry hooks go here


@effect(FlowRunFailed)
async def on_flow_failed(action, store):
    """Handle flow failure — potential retry or notification."""
    pass  # placeholder — retry logic and failure notification go here


@effect(NodeFailed)
async def on_node_failed(action, store):
    """Track node failures for debugging."""
    pass  # placeholder — node-level failure tracking and alerting go here


register_effects(
    nodeflow_store,
    on_flow_completed,
    on_flow_failed,
    on_node_failed,
)

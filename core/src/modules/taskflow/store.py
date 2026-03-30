"""Taskflow state management — FeatureStore for task dispatch and quests."""

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import update_in
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

# ── Actions ──────────────────────────────────────────────────────────────

TaskCreated = create_action("taskflow.task.created")
TaskUpdated = create_action("taskflow.task.updated")
TaskCompleted = create_action("taskflow.task.completed")
TaskStatusChanged = create_action("taskflow.task.status_changed")
TaskDeleted = create_action("taskflow.task.deleted")
ReportGenerated = create_action("taskflow.report.generated")

# ── Reducer ──────────────────────────────────────────────────────────────

taskflow_reducer = create_reducer(
    {"tasks": {}, "completed_count": 0, "deleted_count": 0},
    on(
        TaskCreated,
        lambda s, a: update_in(
            s,
            ["tasks", a.payload.get("id", "") if a.payload else ""],
            lambda _: a.payload,
        ),
    ),
    on(
        TaskUpdated,
        lambda s, a: update_in(
            s,
            ["tasks", a.payload.get("id", "") if a.payload else ""],
            lambda existing: {**(existing or {}), **(a.payload or {})},
        ),
    ),
    on(
        TaskStatusChanged,
        lambda s, a: update_in(
            s,
            ["tasks", a.payload.get("id", "") if a.payload else ""],
            lambda existing: {
                **(existing or {}),
                "status": a.payload.get("status") if a.payload else None,
            },
        ),
    ),
    on(
        TaskCompleted,
        lambda s, a: s.set("completed_count", s["completed_count"] + 1),
    ),
    on(
        TaskDeleted,
        lambda s, a: s.set("deleted_count", s["deleted_count"] + 1),
    ),
    on(
        ReportGenerated,
        lambda s, a: s,  # report generation is side-effect only — no state change
    ),
)

# ── Store ─────────────────────────────────────────────────────────────────

taskflow_store: FeatureStore = FeatureStore("taskflow", taskflow_reducer)

# ── Selectors ─────────────────────────────────────────────────────────────

select_tasks = create_selector(lambda s: dict(s["tasks"]) if s["tasks"] else {})

select_active_tasks = create_selector(
    lambda s: {
        k: v for k, v in s["tasks"].items() if v and v.get("status") not in ("completed", "deleted")
    }
)

select_taskflow_stats = create_selector(
    lambda s: {
        "total_tasks": len(s["tasks"]),
        "completed_count": s["completed_count"],
        "deleted_count": s["deleted_count"],
    }
)

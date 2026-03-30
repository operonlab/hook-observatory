"""Taskflow state management — FeatureStore for task dispatch and quests."""

import logging

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import update_in
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect, register_effects

logger = logging.getLogger(__name__)

# ── Actions ──────────────────────────────────────────────────────────────

TaskCreated = create_action("taskflow.task.created")
TaskUpdated = create_action("taskflow.task.updated")
TaskCompleted = create_action("taskflow.task.completed")
TaskStatusChanged = create_action("taskflow.task.status_changed")
TaskDeleted = create_action("taskflow.task.deleted")
ReportGenerated = create_action("taskflow.report.generated")
StateTransitioned = create_action("taskflow.state.transitioned")

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
    on(
        StateTransitioned,
        lambda s, a: s,  # state transition is side-effect only — no store state change
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

# ── Effects ───────────────────────────────────────────────────────────────


@effect(TaskCompleted)
async def on_task_completed(action, store):
    """Log task completion for rewards and notification tracking."""
    payload = action.payload or {}
    logger.info(
        "taskflow.task.completed",
        extra={
            "task_id": payload.get("id"),
            "title": payload.get("title"),
            "completed_by": payload.get("completed_by"),
        },
    )


@effect(StateTransitioned, store=taskflow_store)
async def publish_state_changed(action, store) -> None:
    """Publish state_changed event to EventBus (replaces emit_state_changed)."""
    payload = action.payload or {}
    module_name = payload.get("module", "taskflow")
    entity_type = payload.get("entity_type", "")
    event_type = f"{module_name}.{entity_type}.state_changed"
    try:
        from src.events.bus import Event, event_bus

        await event_bus.publish(
            Event(
                type=event_type,
                data={
                    "entity_id": payload.get("entity_id"),
                    "old_state": payload.get("old_state"),
                    "new_state": payload.get("new_state"),
                    **{
                        k: v
                        for k, v in payload.items()
                        if k not in ("module", "entity_type", "entity_id", "old_state", "new_state")
                    },
                },
                source=f"{module_name}.store",
                user_id=payload.get("user_id"),
            )
        )
    except Exception:
        logger.debug("EventBus publish failed for %s", event_type, exc_info=True)


register_effects(
    taskflow_store,
    on_task_completed,
    publish_state_changed,
)

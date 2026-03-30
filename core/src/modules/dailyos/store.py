"""DailyOS FeatureStore — daily plan state management.

NgRx-style store for the dailyos module:
- Tracks today's plan, active method, and completion count
- Effect wraps the on_plan_completed → memvault extraction from events.py
"""

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import to_immutable
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect, register_effects

# ── Actions ──────────────────────────────────────────────────────────────

MethodCreated = create_action("dailyos.method.created")
MethodUpdated = create_action("dailyos.method.updated")
MethodDeleted = create_action("dailyos.method.deleted")
MethodSwitched = create_action("dailyos.method.switched")
PlanCreated = create_action("dailyos.plan.created")
PlanUpdated = create_action("dailyos.plan.updated")
PlanCompleted = create_action("dailyos.plan.completed")
ReviewSubmitted = create_action("dailyos.review.submitted")

# ── Reducer ──────────────────────────────────────────────────────────────

dailyos_reducer = create_reducer(
    {"today_plan": None, "active_method": None, "completion_count": 0},
    on(
        PlanCreated,
        lambda s, a: s.set("today_plan", to_immutable(a.payload) if a.payload else None),
    ),
    on(
        PlanCompleted,
        lambda s, a: s.set("completion_count", s["completion_count"] + 1),
    ),
    on(
        MethodSwitched,
        lambda s, a: s.set(
            "active_method",
            a.payload.get("method_id") if a.payload else None,
        ),
    ),
)

# ── Store ─────────────────────────────────────────────────────────────────

dailyos_store: FeatureStore = FeatureStore("dailyos", dailyos_reducer)

# ── Effects ───────────────────────────────────────────────────────────────


@effect(PlanCompleted, store=dailyos_store)
async def plan_completed_effect(action, store):
    """Wrap on_plan_completed → memvault behavioral extraction from events.py.

    The EventBus subscriber in events.py handles the actual Memvault write.
    This effect bridges the store dispatch to the existing handler so the
    store's effect registry mirrors the EventBus subscription for observability.
    """
    from src.events.bus import Event

    from .events import on_plan_completed

    if action.payload:
        event = Event(
            type=action.type,
            data=action.payload if isinstance(action.payload, dict) else {},
            source="dailyos_store",
        )
        await on_plan_completed(event)


register_effects(dailyos_store, plan_completed_effect)

# ── Selectors ─────────────────────────────────────────────────────────────

select_today_plan = create_selector(
    lambda state: dict(state["today_plan"]) if state["today_plan"] is not None else None
)

select_completion_rate = create_selector(
    lambda state: {
        "completion_count": state["completion_count"],
        "has_plan": state["today_plan"] is not None,
        "active_method": state["active_method"],
    }
)

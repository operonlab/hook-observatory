"""Briefing state management — FeatureStore + NgRx patterns.

Tracks today's briefing, analysts map, follow-ups, and completed count.
Does NOT replicate DB — thin reactive layer on top of services.py.
"""

from __future__ import annotations

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import batch_update, to_immutable, update_in
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

# ── 1. Actions ────────────────────────────────────────────────────────────

DailyCompleted = create_action("briefing.daily.completed")
DailyFailed = create_action("briefing.daily.failed")
FollowUpAsked = create_action("briefing.follow_up.asked")
FollowUpAnswered = create_action("briefing.follow_up.answered")
AnalystCreated = create_action("briefing.analyst.created")
TopicUpdated = create_action("briefing.topic.updated")

# ── 2. Reducer ────────────────────────────────────────────────────────────

_MAX_FOLLOW_UPS = 50


def _handle_daily_completed(state, action):
    """Set today_briefing snapshot + increment completed_count."""
    payload = action.payload or {}
    briefing_data = to_immutable(
        {
            "id": payload.get("id"),
            "date": payload.get("date"),
            "status": "completed",
            "topic_count": payload.get("topic_count"),
            "completed_at": payload.get("completed_at"),
        }
    )
    return batch_update(
        state,
        {
            "today_briefing": briefing_data,
            "completed_count": state["completed_count"] + 1,
        },
    )


def _handle_analyst_created(state, action):
    """Add analyst to analysts map by id."""
    payload = action.payload or {}
    analyst_id = payload.get("id")
    if not analyst_id:
        return state
    analysts = state.get("analysts", {})
    analyst_entry = to_immutable(
        {
            "id": analyst_id,
            "name": payload.get("name"),
            "role": payload.get("role"),
            "topic_id": payload.get("topic_id"),
            "created_at": payload.get("created_at"),
        }
    )
    return update_in(state, ["analysts"], lambda _: analysts.set(analyst_id, analyst_entry))


def _handle_follow_up_asked(state, action):
    """Append new follow-up question to follow_ups (capped at 50)."""
    payload = action.payload or {}
    follow_up_id = payload.get("id")
    if not follow_up_id:
        return state
    follow_ups = state.get("follow_ups", ())
    entry = to_immutable(
        {
            "id": follow_up_id,
            "question": payload.get("question"),
            "briefing_id": payload.get("briefing_id"),
            "answered": False,
            "created_at": payload.get("created_at"),
        }
    )
    new_follow_ups = (entry, *follow_ups)[:_MAX_FOLLOW_UPS]
    return state.set("follow_ups", new_follow_ups)


def _handle_follow_up_answered(state, action):
    """Mark follow-up as answered in follow_ups list."""
    payload = action.payload or {}
    follow_up_id = payload.get("id")
    if not follow_up_id:
        return state
    follow_ups = state.get("follow_ups", ())
    updated = tuple(
        fu.set("answered", True) if fu.get("id") == follow_up_id else fu for fu in follow_ups
    )
    return state.set("follow_ups", updated)


briefing_reducer = create_reducer(
    {
        "today_briefing": None,
        "analysts": {},
        "follow_ups": [],
        "completed_count": 0,
    },
    on(DailyCompleted, _handle_daily_completed),
    on(DailyFailed, lambda s, a: s),
    on(AnalystCreated, _handle_analyst_created),
    on(FollowUpAsked, _handle_follow_up_asked),
    on(FollowUpAnswered, _handle_follow_up_answered),
    on(TopicUpdated, lambda s, a: s),
)

# ── 3. Selectors ─────────────────────────────────────────────────────────

select_today_briefing = create_selector(lambda s: s["today_briefing"])
select_analysts = create_selector(lambda s: s["analysts"])
select_follow_ups = create_selector(lambda s: s["follow_ups"])
select_completed_count = create_selector(lambda s: s["completed_count"])
select_pending_follow_ups = create_selector(
    select_follow_ups,
    result_fn=lambda fus: tuple(fu for fu in fus if not fu.get("answered")),
)

# ── 4. Store ──────────────────────────────────────────────────────────────

briefing_store: FeatureStore = FeatureStore("briefing", briefing_reducer)

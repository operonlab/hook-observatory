"""Matchcore state management — FeatureStore + NgRx patterns.

Tracks pending matches, completed matches, and score cache.
Does NOT replicate DB — thin reactive layer on top of services.py.
"""

from __future__ import annotations

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import batch_update, to_immutable, update_in
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

# ── 1. Actions ────────────────────────────────────────────────────────────

MatchRequested = create_action("matchcore.match.requested")
MatchFound = create_action("matchcore.match.found")
ScoreCalculated = create_action("matchcore.score.calculated")

# ── 2. Reducer ────────────────────────────────────────────────────────────


def _handle_match_requested(state, action):
    """Add match request to pending_matches."""
    payload = action.payload or {}
    match_id = payload.get("id") or payload.get("match_id")
    if not match_id:
        return state
    pending = state.get("pending_matches", {})
    match_entry = to_immutable(
        {
            "id": match_id,
            "candidate_id": payload.get("candidate_id"),
            "job_id": payload.get("job_id"),
            "requested_at": payload.get("requested_at"),
            "status": "pending",
        }
    )
    return update_in(state, ["pending_matches"], lambda _: pending.set(match_id, match_entry))


def _handle_match_found(state, action):
    """Move match from pending to completed."""
    payload = action.payload or {}
    match_id = payload.get("id") or payload.get("match_id")
    if not match_id:
        return state
    pending = state.get("pending_matches", {})
    completed = state.get("completed_matches", {})

    # Move from pending → completed
    match_data = pending.get(match_id)
    if match_data is None:
        # May have been dispatched directly without pending entry
        match_data = to_immutable(
            {
                "id": match_id,
                "candidate_id": payload.get("candidate_id"),
                "job_id": payload.get("job_id"),
            }
        )

    completed_entry = match_data.set("status", "found").set("found_at", payload.get("found_at"))

    new_completed = completed.set(match_id, completed_entry)

    if match_id in pending:
        e = pending.mutate()
        del e[match_id]
        new_pending = e.finish()
    else:
        new_pending = pending

    return batch_update(
        state,
        {
            "pending_matches": new_pending,
            "completed_matches": new_completed,
        },
    )


def _handle_score_calculated(state, action):
    """Store score in scores cache."""
    payload = action.payload or {}
    match_id = payload.get("match_id") or payload.get("id")
    if not match_id:
        return state
    scores = state.get("scores", {})
    score_entry = to_immutable(
        {
            "match_id": match_id,
            "score": payload.get("score"),
            "breakdown": payload.get("breakdown"),
            "calculated_at": payload.get("calculated_at"),
        }
    )
    return update_in(state, ["scores"], lambda _: scores.set(match_id, score_entry))


matchcore_reducer = create_reducer(
    {
        "pending_matches": {},
        "completed_matches": {},
        "scores": {},
    },
    on(MatchRequested, _handle_match_requested),
    on(MatchFound, _handle_match_found),
    on(ScoreCalculated, _handle_score_calculated),
)

# ── 3. Selectors ─────────────────────────────────────────────────────────

select_pending_matches = create_selector(lambda s: s["pending_matches"])
select_completed_matches = create_selector(lambda s: s["completed_matches"])
select_scores = create_selector(lambda s: s["scores"])
select_pending_count = create_selector(
    select_pending_matches,
    result_fn=lambda pending: len(pending),
)
select_top_scores = create_selector(
    select_scores,
    result_fn=lambda scores: sorted(
        scores.values(),
        key=lambda x: x.get("score", 0),
        reverse=True,
    )[:10],
)

# ── 4. Store ──────────────────────────────────────────────────────────────

matchcore_store: FeatureStore = FeatureStore("matchcore", matchcore_reducer)

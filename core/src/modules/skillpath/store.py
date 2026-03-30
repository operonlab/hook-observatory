"""Skillpath state management — FeatureStore + NgRx patterns.

Tracks unlocked skills, path progress, and milestone history.
Does NOT replicate DB — thin reactive layer on top of services.py.
"""

from __future__ import annotations

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import to_immutable, update_in
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

# ── 1. Actions ────────────────────────────────────────────────────────────

SkillUnlocked = create_action("skillpath.skill.unlocked")
PathProgressed = create_action("skillpath.path.progressed")
MilestoneReached = create_action("skillpath.milestone.reached")

# ── 2. Reducer ────────────────────────────────────────────────────────────

_MAX_MILESTONES = 50


def _handle_skill_unlocked(state, action):
    """Add skill to unlocked_skills map by id."""
    payload = action.payload or {}
    skill_id = payload.get("id") or payload.get("skill_id")
    if not skill_id:
        return state
    unlocked = state.get("unlocked_skills", {})
    skill_entry = to_immutable(
        {
            "id": skill_id,
            "name": payload.get("name"),
            "path_id": payload.get("path_id"),
            "level": payload.get("level"),
            "unlocked_at": payload.get("unlocked_at"),
        }
    )
    return update_in(state, ["unlocked_skills"], lambda _: unlocked.set(skill_id, skill_entry))


def _handle_path_progressed(state, action):
    """Update path progress percentage."""
    payload = action.payload or {}
    path_id = payload.get("path_id") or payload.get("id")
    if not path_id:
        return state
    progress = state.get("path_progress", {})
    progress_entry = to_immutable(
        {
            "path_id": path_id,
            "name": payload.get("name"),
            "progress_pct": payload.get("progress_pct", 0),
            "completed_skills": payload.get("completed_skills", 0),
            "total_skills": payload.get("total_skills", 0),
            "updated_at": payload.get("updated_at"),
        }
    )
    return update_in(state, ["path_progress"], lambda _: progress.set(path_id, progress_entry))


def _handle_milestone_reached(state, action):
    """Prepend milestone to milestones history (capped at 50)."""
    payload = action.payload or {}
    milestone_id = payload.get("id") or payload.get("milestone_id")
    if not milestone_id:
        return state
    milestones = state.get("milestones", ())
    entry = to_immutable(
        {
            "id": milestone_id,
            "name": payload.get("name"),
            "path_id": payload.get("path_id"),
            "reached_at": payload.get("reached_at"),
        }
    )
    new_milestones = (entry, *milestones)[:_MAX_MILESTONES]
    return state.set("milestones", new_milestones)


skillpath_reducer = create_reducer(
    {
        "unlocked_skills": {},
        "path_progress": {},
        "milestones": [],
    },
    on(SkillUnlocked, _handle_skill_unlocked),
    on(PathProgressed, _handle_path_progressed),
    on(MilestoneReached, _handle_milestone_reached),
)

# ── 3. Selectors ─────────────────────────────────────────────────────────

select_unlocked_skills = create_selector(lambda s: s["unlocked_skills"])
select_path_progress = create_selector(lambda s: s["path_progress"])
select_milestones = create_selector(lambda s: s["milestones"])
select_unlocked_skill_count = create_selector(
    select_unlocked_skills,
    result_fn=lambda skills: len(skills),
)
select_completed_paths = create_selector(
    select_path_progress,
    result_fn=lambda paths: {k: v for k, v in paths.items() if v.get("progress_pct", 0) >= 100},
)

# ── 4. Store ──────────────────────────────────────────────────────────────

skillpath_store: FeatureStore = FeatureStore("skillpath", skillpath_reducer)

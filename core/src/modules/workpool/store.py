"""Workpool state management — FeatureStore + NgRx patterns.

Tracks allocated resources, capacity alert count, and total allocated units.
Does NOT replicate DB — thin reactive layer on top of services.py.
"""

from __future__ import annotations

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import batch_update, to_immutable
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore

# ── 1. Actions ────────────────────────────────────────────────────────────

ResourceAllocated = create_action("workpool.resource.allocated")
ResourceReleased = create_action("workpool.resource.released")
CapacityExceeded = create_action("workpool.capacity.exceeded")

# ── 2. Reducer ────────────────────────────────────────────────────────────


def _handle_resource_allocated(state, action):
    """Add resource to allocated map + update total_allocated."""
    payload = action.payload or {}
    resource_id = payload.get("id") or payload.get("resource_id")
    if not resource_id:
        return state
    allocated = state.get("allocated", {})
    units = payload.get("units", 1)
    resource_entry = to_immutable(
        {
            "id": resource_id,
            "name": payload.get("name"),
            "type": payload.get("type"),
            "units": units,
            "allocated_by": payload.get("allocated_by"),
            "allocated_at": payload.get("allocated_at"),
        }
    )
    new_allocated = allocated.set(resource_id, resource_entry)
    new_total = state["total_allocated"] + units
    return batch_update(
        state,
        {
            "allocated": new_allocated,
            "total_allocated": new_total,
        },
    )


def _handle_resource_released(state, action):
    """Remove resource from allocated map + update total_allocated."""
    payload = action.payload or {}
    resource_id = payload.get("id") or payload.get("resource_id")
    if not resource_id:
        return state
    allocated = state.get("allocated", {})
    if resource_id not in allocated:
        return state
    units = allocated[resource_id].get("units", 1)
    e = allocated.mutate()
    del e[resource_id]
    new_allocated = e.finish()
    new_total = max(0, state["total_allocated"] - units)
    return batch_update(
        state,
        {
            "allocated": new_allocated,
            "total_allocated": new_total,
        },
    )


def _handle_capacity_exceeded(state, action):
    """Increment capacity_alerts counter."""
    return state.set("capacity_alerts", state["capacity_alerts"] + 1)


workpool_reducer = create_reducer(
    {
        "allocated": {},
        "capacity_alerts": 0,
        "total_allocated": 0,
    },
    on(ResourceAllocated, _handle_resource_allocated),
    on(ResourceReleased, _handle_resource_released),
    on(CapacityExceeded, _handle_capacity_exceeded),
)

# ── 3. Selectors ─────────────────────────────────────────────────────────

select_allocated = create_selector(lambda s: s["allocated"])
select_capacity_alerts = create_selector(lambda s: s["capacity_alerts"])
select_total_allocated = create_selector(lambda s: s["total_allocated"])
select_capacity_utilization = create_selector(
    select_allocated,
    select_total_allocated,
    result_fn=lambda allocated, total: {
        "resource_count": len(allocated),
        "total_units": total,
    },
)

# ── 4. Store ──────────────────────────────────────────────────────────────

workpool_store: FeatureStore = FeatureStore("workpool", workpool_reducer)

"""Workpool actions — type-safe event definitions."""

from src.shared.actions import create_action

# ── Actions ──────────────────────────────────────────────────────────────

ResourceAllocated = create_action("workpool.resource.allocated")
ResourceReleased = create_action("workpool.resource.released")
CapacityExceeded = create_action("workpool.capacity.exceeded")

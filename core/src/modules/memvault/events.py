"""Memvault event handlers — cache invalidation + event subscribers."""

from src.events.types import MemvaultEvents
from src.shared.cache import register_invalidation

# --- Cache invalidation wiring ---

register_invalidation(
    module="memvault",
    operations=["list_tags"],
    events=[
        MemvaultEvents.MEMORY_STORED,
        MemvaultEvents.MEMORY_UPDATED,
        MemvaultEvents.MEMORY_DELETED,
    ],
)

register_invalidation(
    module="memvault",
    operations=["profile_score"],
    events=[
        MemvaultEvents.PROFILE_UPDATED,
    ],
)

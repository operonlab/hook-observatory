"""Intelflow event handlers — cache invalidation."""

from src.events.types import IntelflowEvents
from src.shared.cache import register_invalidation

# --- Cache invalidation wiring ---

register_invalidation(
    module="intelflow",
    operations=["list_topics"],
    events=[
        IntelflowEvents.REPORT_CREATED,
        IntelflowEvents.TOPIC_CREATED,
    ],
)

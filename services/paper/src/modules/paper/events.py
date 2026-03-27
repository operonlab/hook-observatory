"""Paper event handlers — cache invalidation."""

from src.events.types import PaperEvents
from src.shared.cache import register_invalidation

# --- Cache invalidation wiring ---

register_invalidation(
    module="paper",
    operations=["dashboard_summary"],
    events=[
        PaperEvents.ARTICLE_CREATED,
        PaperEvents.ARTICLE_DELETED,
        PaperEvents.DIGEST_GENERATED,
    ],
)

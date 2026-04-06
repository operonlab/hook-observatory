"""DocVault event handlers — cache invalidation wiring.

Cross-module reactive pipes will be added in Phase 2+.
"""

from src.events.types import DocvaultEvents
from src.shared.cache import register_invalidation

# --- Cache invalidation wiring ---

register_invalidation(
    module="docvault",
    operations=["dashboard_summary"],
    events=[
        DocvaultEvents.DOCUMENT_CREATED,
        DocvaultEvents.DOCUMENT_PUBLISHED,
        DocvaultEvents.DOCUMENT_ARCHIVED,
        DocvaultEvents.QA_EXECUTED,
        DocvaultEvents.COVERAGE_GAP_DETECTED,
    ],
)

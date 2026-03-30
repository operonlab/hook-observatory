"""Capture FeatureStore — enrichment pipeline state management.

NgRx-style store for the capture module:
- Tracks pending enrichments (keyed by capture ID)
- Counts enriched and promoted captures
- Effect wraps the auto-enrich handler from events.py
"""

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import update_in
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect, register_effects

# ── Actions ──────────────────────────────────────────────────────────────

CaptureCreated = create_action("capture.created")
CaptureEnriched = create_action("capture.enriched")
CapturePromoted = create_action("capture.promoted")
CaptureExpired = create_action("capture.expired")

# ── Reducer ──────────────────────────────────────────────────────────────

capture_reducer = create_reducer(
    {"pending_enrichments": {}, "enriched_count": 0, "promoted_count": 0},
    on(
        CaptureCreated,
        lambda s, a: update_in(
            s,
            ["pending_enrichments", a.payload.get("id", "") if a.payload else ""],
            lambda _: a.payload,
        ),
    ),
    on(
        CaptureEnriched,
        lambda s, a: s.set("enriched_count", s["enriched_count"] + 1),
    ),
    on(
        CapturePromoted,
        lambda s, a: s.set("promoted_count", s["promoted_count"] + 1),
    ),
)

# ── Store ─────────────────────────────────────────────────────────────────

capture_store: FeatureStore = FeatureStore("capture", capture_reducer)

# ── Effects ───────────────────────────────────────────────────────────────


@effect(CaptureCreated, store=capture_store)
async def auto_enrich_effect(action, store):
    """Wrap on_capture_created_auto_enrich from events.py.

    The EventBus subscriber in events.py handles the actual enrichment logic.
    This effect is a no-op bridge so the store's effect registry mirrors
    the EventBus subscription for observability.
    """
    from src.events.bus import Event

    from .events import on_capture_created_auto_enrich

    if action.payload:
        event = Event(
            type=action.type,
            data=action.payload if isinstance(action.payload, dict) else {},
            source="capture_store",
        )
        await on_capture_created_auto_enrich(event)


register_effects(capture_store, auto_enrich_effect)

# ── Selectors ─────────────────────────────────────────────────────────────

select_pending_enrichments = create_selector(
    lambda state: dict(state["pending_enrichments"]) if state["pending_enrichments"] else {}
)

select_enrichment_stats = create_selector(
    lambda state: {
        "enriched_count": state["enriched_count"],
        "promoted_count": state["promoted_count"],
        "pending_count": len(state["pending_enrichments"]),
    }
)

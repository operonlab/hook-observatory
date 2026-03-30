"""Notification state management — FeatureStore with push delivery effects."""

from src.shared.actions import create_action, create_reducer, on
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect, register_effects

# ── Actions ──────────────────────────────────────────────────────────────

PushDelivered = create_action("notification.push.delivered")
PushFailed = create_action("notification.push.failed")
SubscriptionCreated = create_action("notification.subscription.created")
SubscriptionRemoved = create_action("notification.subscription.removed")

# ── Reducer ──────────────────────────────────────────────────────────────

notification_reducer = create_reducer(
    {"delivered_count": 0, "failed_count": 0, "subscription_count": 0},
    on(
        PushDelivered,
        lambda s, a: s.set("delivered_count", s["delivered_count"] + 1),
    ),
    on(
        PushFailed,
        lambda s, a: s.set("failed_count", s["failed_count"] + 1),
    ),
    on(
        SubscriptionCreated,
        lambda s, a: s.set("subscription_count", s["subscription_count"] + 1),
    ),
    on(
        SubscriptionRemoved,
        lambda s, a: s.set(
            "subscription_count",
            max(0, s["subscription_count"] - 1),
        ),
    ),
)

# ── Store ─────────────────────────────────────────────────────────────────

notification_store: FeatureStore = FeatureStore("notification", notification_reducer)

# ── Effects ───────────────────────────────────────────────────────────────


@effect(PushDelivered, store=notification_store)
async def on_push_delivered(action, store):
    """Bridge: mirrors EventBus on_mapped_event for finance.budget.exceeded push."""
    # Delivery tracking only — actual push handled by events.py EventBus subscriber
    pass


@effect(PushFailed, store=notification_store)
async def on_push_failed(action, store):
    """Bridge: log failed push attempts for observability."""
    import logging

    logger = logging.getLogger(__name__)
    logger.warning(
        "notification.push.failed",
        extra={"payload": action.payload},
    )


@effect(SubscriptionCreated, store=notification_store)
async def on_subscription_created(action, store):
    """Bridge: mirrors EventBus subscription tracking."""
    pass


@effect(SubscriptionRemoved, store=notification_store)
async def on_subscription_removed(action, store):
    """Bridge: mirrors EventBus subscription removal tracking."""
    pass


register_effects(
    notification_store,
    on_push_delivered,
    on_push_failed,
    on_subscription_created,
    on_subscription_removed,
)

# ── Selectors ─────────────────────────────────────────────────────────────

select_notification_stats = create_selector(
    lambda s: {
        "delivered_count": s["delivered_count"],
        "failed_count": s["failed_count"],
        "subscription_count": s["subscription_count"],
    }
)

select_delivery_rate = create_selector(
    lambda s: (
        s["delivered_count"] / (s["delivered_count"] + s["failed_count"])
        if (s["delivered_count"] + s["failed_count"]) > 0
        else 1.0
    )
)

"""Intelflow state management — FeatureStore for reports, topics, and feeds."""

import logging

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import batch_update
from src.shared.middleware import PerformanceMiddleware
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect, register_effects

logger = logging.getLogger(__name__)

# ── Actions ──────────────────────────────────────────────────────────────

ReportCreated = create_action("intelflow.report.created")
ReportUpdated = create_action("intelflow.report.updated")
ReportDeleted = create_action("intelflow.report.deleted")
TopicCreated = create_action("intelflow.topic.created")
FeedAdded = create_action("intelflow.feed.added")
FeedFetched = create_action("intelflow.feed.fetched")

# ── Reducer ──────────────────────────────────────────────────────────────

intelflow_reducer = create_reducer(
    {"report_count": 0, "topic_count": 0, "tags": (), "recent_reports": []},
    on(
        ReportCreated,
        lambda s, a: batch_update(
            s,
            {
                "report_count": s["report_count"] + 1,
                "recent_reports": (a.payload, *tuple(s["recent_reports"])[:49]),
            },
        ),
    ),
    on(
        ReportDeleted,
        lambda s, a: s.set("report_count", max(0, s["report_count"] - 1)),
    ),
    on(
        TopicCreated,
        lambda s, a: s.set("topic_count", s["topic_count"] + 1),
    ),
    on(
        ReportUpdated,
        lambda s, a: s,  # updates are transient — list queries hit DB
    ),
    on(
        FeedAdded,
        lambda s, a: s,  # feed count derived from DB — no in-memory state
    ),
    on(
        FeedFetched,
        lambda s, a: s,  # fetch events are transient — no state change
    ),
)

# ── Store ─────────────────────────────────────────────────────────────────

intelflow_store: FeatureStore = FeatureStore(
    "intelflow",
    intelflow_reducer,
    middlewares=[PerformanceMiddleware(warn_threshold_ms=200.0)],
)

# ── Selectors ─────────────────────────────────────────────────────────────

select_report_count = create_selector(
    lambda s: s.get("report_count", 0) if isinstance(s, dict) else s["report_count"]
)

select_all_tags = create_selector(
    lambda s: s.get("tags", []) if isinstance(s, dict) else list(s["tags"])
)

select_topic_graph = create_selector(
    lambda s: s.get("topic_graph", {}) if isinstance(s, dict) else {}
)

select_feed_count = create_selector(lambda s: s.get("feed_count", 0) if isinstance(s, dict) else 0)

select_latest_report_id = create_selector(
    lambda s: s.get("latest_report_id") if isinstance(s, dict) else None
)

select_active_topics = create_selector(
    lambda s: [
        t for t in (s.get("topics", []) if isinstance(s, dict) else []) if t.get("active", True)
    ]
)

select_recent_reports = create_selector(
    lambda s: list(s["recent_reports"]) if not isinstance(s, dict) else s.get("recent_reports", [])
)

select_intelflow_stats = create_selector(
    lambda s: {
        "report_count": s["report_count"] if not isinstance(s, dict) else s.get("report_count", 0),
        "topic_count": s["topic_count"] if not isinstance(s, dict) else s.get("topic_count", 0),
    }
)

# ── Effects ───────────────────────────────────────────────────────────────


@effect(ReportCreated)
async def on_report_created(action, store):
    """Log new report creation for cache invalidation tracking."""
    payload = action.payload or {}
    logger.info(
        "intelflow.report.created",
        extra={"report_id": payload.get("id"), "title": payload.get("title")},
    )


@effect(TopicCreated)
async def on_topic_created(action, store):
    """Log new topic creation."""
    payload = action.payload or {}
    logger.info(
        "intelflow.topic.created",
        extra={"topic_id": payload.get("id"), "name": payload.get("name")},
    )


register_effects(
    intelflow_store,
    on_report_created,
    on_topic_created,
)

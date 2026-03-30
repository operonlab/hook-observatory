"""Intelflow state management — selectors for dashboard/topic caching.

State comes from DB — selectors cache computed projections (no reducer needed).
"""

from src.shared.actions import create_action
from src.shared.selectors import create_selector

# ── Actions ──────────────────────────────────────────────────────────────

ReportCreated = create_action("intelflow.report.created")
ReportUpdated = create_action("intelflow.report.updated")
ReportDeleted = create_action("intelflow.report.deleted")
TopicCreated = create_action("intelflow.topic.created")
FeedAdded = create_action("intelflow.feed.added")
FeedFetched = create_action("intelflow.feed.fetched")

# ── Selectors (DB-backed — no reducer, selectors cache computations) ──────

select_report_count = create_selector(lambda s: s.get("report_count", 0))

select_all_tags = create_selector(lambda s: s.get("tags", []))

select_topic_graph = create_selector(lambda s: s.get("topic_graph", {}))

select_feed_count = create_selector(lambda s: s.get("feed_count", 0))

select_latest_report_id = create_selector(lambda s: s.get("latest_report_id"))

select_active_topics = create_selector(
    lambda s: [t for t in s.get("topics", []) if t.get("active", True)]
)

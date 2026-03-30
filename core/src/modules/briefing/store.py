"""Briefing actions — type-safe event definitions."""

from src.shared.actions import create_action

# ── Actions ──────────────────────────────────────────────────────────────

DailyCompleted = create_action("briefing.daily.completed")
DailyFailed = create_action("briefing.daily.failed")
FollowUpAsked = create_action("briefing.follow_up.asked")
FollowUpAnswered = create_action("briefing.follow_up.answered")
AnalystCreated = create_action("briefing.analyst.created")
TopicUpdated = create_action("briefing.topic.updated")

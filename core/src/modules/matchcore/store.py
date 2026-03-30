"""Matchcore actions — type-safe event definitions."""

from src.shared.actions import create_action

# ── Actions ──────────────────────────────────────────────────────────────

MatchRequested = create_action("matchcore.match.requested")
MatchFound = create_action("matchcore.match.found")
ScoreCalculated = create_action("matchcore.score.calculated")

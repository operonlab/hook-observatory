"""Ideagraph actions — type-safe event definitions."""

from src.shared.actions import create_action

# ── Actions ──────────────────────────────────────────────────────────────

SparkCaptured = create_action("ideagraph.spark.captured")
SparkRefined = create_action("ideagraph.spark.refined")
LinkSuggested = create_action("ideagraph.link.suggested")
LinkVerified = create_action("ideagraph.link.verified")

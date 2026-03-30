"""Skillpath actions — type-safe event definitions."""

from src.shared.actions import create_action

# ── Actions ──────────────────────────────────────────────────────────────

SkillUnlocked = create_action("skillpath.skill.unlocked")
PathProgressed = create_action("skillpath.path.progressed")
MilestoneReached = create_action("skillpath.milestone.reached")

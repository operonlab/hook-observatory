"""Auto Survey — FeatureStore (ACTION depth only).

Defines action creators for survey pipeline lifecycle events.
No reducer or store instance at this depth — actions are dispatched
by the orchestrator into a parent store if needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from src.shared.actions import create_action

# ── Actions ──────────────────────────────────────────────────────────────────

SurveyStarted = create_action("survey.started")
SurveyCompleted = create_action("survey.completed")
QuestionAnswered = create_action("survey.question.answered")
SurveyFailed = create_action("survey.failed")

"""Auto Survey — FeatureStore (FULL depth).

Tracks survey pipeline lifecycle: recon → analyze → fill phases,
per-person submission results, and failure/success counts.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import batch_update
from src.shared.middleware import LoggerMiddleware
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect, register_effects

logger = logging.getLogger(__name__)

# ── Actions ──────────────────────────────────────────────────────────────────

SurveyStarted = create_action("survey.started")
SurveyCompleted = create_action("survey.completed")
QuestionAnswered = create_action("survey.question.answered")
SurveyFailed = create_action("survey.failed")

# ── Reducer ──────────────────────────────────────────────────────────────────


def _p(action):
    """Safe payload accessor."""
    return action.payload or {}


survey_reducer = create_reducer(
    {
        "current_survey": None,
        "completed_count": 0,
        "failed_count": 0,
        "questions_answered": 0,
    },
    on(
        SurveyStarted,
        lambda s, a: batch_update(
            s,
            {
                "current_survey": _p(a),
            },
        ),
    ),
    on(
        SurveyCompleted,
        lambda s, a: batch_update(
            s,
            {
                "completed_count": s["completed_count"] + 1,
                "current_survey": None,
            },
        ),
    ),
    on(
        SurveyFailed,
        lambda s, a: batch_update(
            s,
            {
                "failed_count": s["failed_count"] + 1,
                "current_survey": None,
            },
        ),
    ),
    on(
        QuestionAnswered,
        lambda s, a: s.set("questions_answered", s["questions_answered"] + 1),
    ),
)

# ── Selectors ────────────────────────────────────────────────────────────────

select_current_survey = create_selector(lambda s: s["current_survey"])
select_completed_count = create_selector(lambda s: s["completed_count"])
select_failed_count = create_selector(lambda s: s["failed_count"])
select_questions_answered = create_selector(lambda s: s["questions_answered"])

select_survey_stats = create_selector(
    lambda s: {
        "completed": s["completed_count"],
        "failed": s["failed_count"],
        "questions_answered": s["questions_answered"],
        "is_active": s["current_survey"] is not None,
    }
)

# ── Store ────────────────────────────────────────────────────────────────────

survey_store = FeatureStore(
    "auto-survey",
    survey_reducer,
    middlewares=[LoggerMiddleware("auto-survey")],
)

# ── Effects ──────────────────────────────────────────────────────────────────


@effect(SurveyCompleted, store=survey_store)
async def log_survey_completed(action, store) -> None:
    """Log survey completion with stats."""
    payload = action.payload or {}
    logger.info(
        "survey.completed",
        extra={
            "survey_type": payload.get("survey_type"),
            "success_count": payload.get("success_count"),
            "total_count": payload.get("total_count"),
        },
    )


@effect(SurveyFailed, store=survey_store)
async def log_survey_failed(action, store) -> None:
    """Log survey failure as warning."""
    payload = action.payload or {}
    logger.warning(
        "survey.failed",
        extra={
            "survey_type": payload.get("survey_type"),
            "reason": payload.get("reason", "unknown"),
        },
    )


register_effects(survey_store, log_survey_completed, log_survey_failed)

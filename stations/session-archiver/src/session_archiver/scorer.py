"""Three-factor weighted scoring algorithm for session archive prioritization.

Scores sessions on a 0-100 scale where higher = more suitable for archiving.

Factors:
    1. Size (weight 40)     - larger files benefit more from compression
    2. Age (weight 35)      - older sessions are safer to archive
    3. Activity (weight 25) - completed, meaningful work that is now idle
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import structlog

from session_archiver.models import ScoreBreakdown, SessionMeta

log = structlog.get_logger(__name__)


def score_session(meta: SessionMeta) -> ScoreBreakdown:
    """Three-factor weighted score (0-100). Higher = more suitable for archiving."""

    now = datetime.now(UTC)
    size_mb = meta.file_size_bytes / (1024 * 1024)
    age_days = (now - meta.last_modified).total_seconds() / 86400

    # 1. Size (weight: 40, range: 0-40)
    #    Sigmoid: <100KB -> ~0, 1MB -> ~4, 10MB -> ~25, 50MB -> ~39
    s_size = 40 * (1 - math.exp(-size_mb / 10))

    # 2. Age (weight: 35, range: 0-35)
    #    Exponential: 3d -> ~11, 7d -> ~22, 14d -> ~31, 30d -> ~35
    s_age = 35 * (1 - math.exp(-age_days / 7))

    # 3. Activity (weight: 25, range: 0-25)
    #    Completed meaningful work that is now idle = high score.
    #    Empty or brand-new sessions = low score.
    if meta.turn_count == 0:
        s_activity = 5.0  # empty session, low priority
    elif age_days < 1:
        s_activity = 0.0  # too fresh, don't archive
    else:
        idle_factor = min(1.0, age_days / 7)  # saturates at 7 days idle
        work_factor = min(1.0, meta.turn_count / 10)  # saturates at 10 turns
        s_activity = 25 * idle_factor * work_factor

    total = s_size + s_age + s_activity

    breakdown = ScoreBreakdown(
        total=total,
        size=round(s_size, 2),
        age=round(s_age, 2),
        activity=round(s_activity, 2),
        compressibility=0.0,  # deprecated — kept for DB compatibility
    )

    log.debug(
        "session_scored",
        session_id=meta.session_id,
        total=round(total, 2),
        size=breakdown.size,
        age=breakdown.age,
        activity=breakdown.activity,
        file_size_mb=round(size_mb, 2),
        age_days=round(age_days, 1),
        turn_count=meta.turn_count,
    )

    return breakdown


def score_all(
    sessions: list[SessionMeta],
) -> list[tuple[SessionMeta, ScoreBreakdown]]:
    """Score all sessions and return sorted by score descending."""

    log.info("scoring_batch_start", session_count=len(sessions))

    scored = [(meta, score_session(meta)) for meta in sessions]
    scored.sort(key=lambda x: x[1].total, reverse=True)

    if scored:
        log.info(
            "scoring_batch_complete",
            session_count=len(scored),
            top_score=round(scored[0][1].total, 2),
            bottom_score=round(scored[-1][1].total, 2),
        )
    else:
        log.info("scoring_batch_complete", session_count=0)

    return scored

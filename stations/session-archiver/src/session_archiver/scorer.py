"""Four-factor weighted scoring algorithm for session archive prioritization.

Scores sessions on a 0-100 scale where higher = more suitable for archiving.

Factors:
    1. Size (weight 30)        - larger files benefit more from compression
    2. Age (weight 25)         - older sessions are safer to archive
    3. Activity (weight 25)    - inactive sessions are better candidates (inverse)
    4. Compressibility (weight 20) - sessions with high user-event ratio compress well
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import structlog

from session_archiver.models import ScoreBreakdown, SessionMeta

log = structlog.get_logger(__name__)


def score_session(meta: SessionMeta) -> ScoreBreakdown:
    """Four-factor weighted score (0-100). Higher = more suitable for archiving."""

    now = datetime.now(UTC)

    # 1. Size (weight: 30, range: 0-30)
    #    Sigmoid curve: <100KB -> ~0, 1MB -> ~8, 10MB -> ~22, 50MB -> ~28
    size_mb = meta.file_size_bytes / (1024 * 1024)
    s_size = 30 * (1 - math.exp(-size_mb / 10))

    # 2. Age (weight: 25, range: 0-25)
    #    Exponential decay: 0 days -> 0, 3 days -> ~5, 7 days -> ~12, 30 days -> ~23
    age_days = (now - meta.last_modified).total_seconds() / 86400
    s_age = 25 * (1 - math.exp(-age_days / 10))

    # 3. Activity -- INVERSE (weight: 25, range: 0-25)
    #    More active = LOWER score (less suitable for archiving)
    activity_raw = (
        (10 if not meta.has_companion else 0)  # never resumed -> +10
        + max(0, 15 - meta.turn_count * 0.5)  # fewer turns -> higher
    )
    s_activity = min(25.0, activity_raw)

    # 4. Compressibility (weight: 20, range: 0-20)
    #    Estimate from user event ratio (base64 screenshots compress well)
    user_ratio = meta.user_event_bytes / max(meta.file_size_bytes, 1)
    s_compress = 20 * user_ratio

    total = s_size + s_age + s_activity + s_compress

    breakdown = ScoreBreakdown(
        total=total,
        size=round(s_size, 2),
        age=round(s_age, 2),
        activity=round(s_activity, 2),
        compressibility=round(s_compress, 2),
    )

    log.debug(
        "session_scored",
        session_id=meta.session_id,
        total=round(total, 2),
        size=breakdown.size,
        age=breakdown.age,
        activity=breakdown.activity,
        compressibility=breakdown.compressibility,
        file_size_mb=round(size_mb, 2),
        age_days=round(age_days, 1),
        turn_count=meta.turn_count,
        has_companion=meta.has_companion,
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

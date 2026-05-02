"""Triple verification governance — UNVERIFIED → VERIFIED auto-promotion (Phase G).

Promotion criteria (any one satisfied):
  1. crag_correct_count >= 3 AND crag_incorrect_count == 0
  2. last_confirmed_at within last 90 days AND access_count >= 5
     (proxy for "stale_claims lint touched it recently and it survives")
  3. (TODO when cascade hit logging matures) cascade recall hit at score
     >= 0.85 at least 2 times in the last 30 days.

Demotion criteria:
  - crag_incorrect_count >= 2 AND crag_correct_count == 0
    (already applied inline in _record_implicit_feedback; this function is
    idempotent and re-asserts the rule for any stragglers).

Designed to be called weekly by a Cronicle job; supports dry_run for safe
first-week observation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .kg_models import KGVerificationRunLog, Triple

logger = logging.getLogger(__name__)


# Tunable thresholds — start conservative; observe first-week stats before
# tightening. Promote to settings.py if multiple call-sites need to override.
CORRECT_COUNT_THRESHOLD = 3
RECENT_CONFIRM_DAYS = 90
RECENT_CONFIRM_ACCESS_THRESHOLD = 5
DEMOTE_INCORRECT_THRESHOLD = 2


@dataclass
class PromotionStats:
    candidates_scanned: int = 0
    promoted_ids: list[str] = field(default_factory=list)
    demoted_ids: list[str] = field(default_factory=list)
    dry_run: bool = True

    @property
    def promoted_count(self) -> int:
        return len(self.promoted_ids)

    @property
    def demoted_count(self) -> int:
        return len(self.demoted_ids)


async def promote_unverified(
    db: AsyncSession,
    *,
    space_id: str = "default",
    batch_size: int = 100,
    dry_run: bool = True,
) -> PromotionStats:
    """Scan unverified triples and promote those meeting verification criteria.

    Also re-asserts the demotion rule for any stragglers that
    _record_implicit_feedback may have missed (transactional race etc.).

    Writes a KGVerificationRunLog audit row regardless of dry_run.
    """
    started = datetime.now(UTC)
    stats = PromotionStats(dry_run=dry_run)
    cutoff = started - timedelta(days=RECENT_CONFIRM_DAYS)

    # ---- Promotion pass ----
    # Criterion 1: 3+ CORRECT verdicts and 0 INCORRECT.
    rule_1 = (Triple.crag_correct_count >= CORRECT_COUNT_THRESHOLD) & (
        Triple.crag_incorrect_count == 0
    )
    # Criterion 2: recently confirmed (CRAG-CORRECT or stale_claims touched
    # last_confirmed_at) and accessed enough times.
    rule_2 = (Triple.last_confirmed_at.is_not(None)) & (
        Triple.last_confirmed_at >= cutoff
    ) & (Triple.access_count >= RECENT_CONFIRM_ACCESS_THRESHOLD)

    from sqlalchemy import select

    eligible = rule_1 | rule_2

    # Single path for both dry_run and apply: SELECT first (with batch_size
    # limit) so the audit-log "candidates_scanned" / "promoted_ids" reflect
    # exactly the same set the apply path would mutate. Previously dry_run was
    # SELECT-limited but apply was UPDATE-without-limit → blast radius of an
    # accidental flip-to-False would be much larger than the dry_run preview
    # suggested (Codex P2).
    promote_sel = (
        select(Triple.id)
        .where(
            Triple.space_id == space_id,
            Triple.verification_status == "unverified",
            Triple.invalid_at.is_(None),
            Triple.deleted_at.is_(None),
            eligible,
        )
        .limit(batch_size)
    )
    promote_ids = list((await db.execute(promote_sel)).scalars().all())
    stats.promoted_ids = promote_ids
    stats.candidates_scanned = len(promote_ids)

    if not dry_run and promote_ids:
        await db.execute(
            update(Triple)
            .where(Triple.id.in_(promote_ids))
            .values(verification_status="verified", verified_at=started)
        )

    # ---- Demotion safety pass ----
    demote_filter = (
        (Triple.space_id == space_id)
        & (Triple.crag_incorrect_count >= DEMOTE_INCORRECT_THRESHOLD)
        & (Triple.crag_correct_count == 0)
        & (Triple.verification_status != "disputed")
        & (Triple.deleted_at.is_(None))
    )
    demote_sel = select(Triple.id).where(demote_filter).limit(batch_size)
    demote_ids = list((await db.execute(demote_sel)).scalars().all())
    stats.demoted_ids = demote_ids

    if not dry_run and demote_ids:
        await db.execute(
            update(Triple)
            .where(Triple.id.in_(demote_ids))
            .values(verification_status="disputed")
        )

    # ---- Audit log ----
    log = KGVerificationRunLog(
        space_id=space_id,
        started_at=started,
        finished_at=datetime.now(UTC),
        dry_run=dry_run,
        candidates_scanned=stats.candidates_scanned,
        promoted_count=stats.promoted_count,
        demoted_count=stats.demoted_count,
        notes=(
            f"thresholds: correct>={CORRECT_COUNT_THRESHOLD} "
            f"recent_days={RECENT_CONFIRM_DAYS} "
            f"recent_access>={RECENT_CONFIRM_ACCESS_THRESHOLD} "
            f"demote_incorrect>={DEMOTE_INCORRECT_THRESHOLD}"
        ),
    )
    db.add(log)
    await db.commit()

    logger.info(
        "promote_unverified: dry_run=%s promoted=%d demoted=%d candidates=%d",
        dry_run,
        stats.promoted_count,
        stats.demoted_count,
        stats.candidates_scanned,
    )
    return stats

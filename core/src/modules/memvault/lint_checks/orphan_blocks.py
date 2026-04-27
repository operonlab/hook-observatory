"""Check 1: orphan_blocks — blocks with no triple pointing at them.

A block is "orphan" if no Triple has source_session matching the block's
source_session AND no entity referenced by the block name is the canonical
subject/object of any active triple. This is a heuristic — wiki-lint defines
orphan as "no incoming wiki-link".
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..kg_models import Triple
from ..models import MemoryBlock


async def check_orphan_blocks(
    db: AsyncSession,
    space_id: str,
    *,
    batch_size: int = 500,
) -> list:
    from ..lint import LintFinding

    findings: list = []

    # 1. Collect set of session_ids referenced by any active triple
    sess_q = (
        select(Triple.source_session)
        .where(
            Triple.space_id == space_id,
            Triple.invalid_at.is_(None),
            Triple.source_session.isnot(None),
        )
        .distinct()
    )
    referenced_sessions = {r[0] for r in (await db.execute(sess_q)).all() if r[0]}

    # 2. Scan active blocks in batches, flag those whose source_session is unknown
    offset = 0
    while True:
        bq = (
            select(MemoryBlock)
            .where(
                MemoryBlock.space_id == space_id,
                MemoryBlock.deleted_at.is_(None),
                MemoryBlock.invalid_at.is_(None),
            )
            .order_by(MemoryBlock.created_at.desc())
            .limit(batch_size)
            .offset(offset)
        )
        rows = (await db.execute(bq)).scalars().all()
        if not rows:
            break

        for block in rows:
            sess = block.source_session
            if sess and sess in referenced_sessions:
                continue
            # No triple ties back to this block — orphan
            findings.append(
                LintFinding(
                    check="orphan_blocks",
                    severity="warning",
                    entity_id=block.id,
                    entity_type="block",
                    message=(
                        f"Block {block.id[:8]} has no incoming triple references "
                        f"(session={sess or 'none'})"
                    ),
                    suggested_action=(
                        "Review whether this block is still needed; if obsolete, "
                        "soft-delete or attach to an existing entity."
                    ),
                    metadata={
                        "block_id": block.id,
                        "source_session": sess,
                        "block_type": block.block_type,
                    },
                )
            )

        if len(rows) < batch_size:
            break
        offset += batch_size

    return findings

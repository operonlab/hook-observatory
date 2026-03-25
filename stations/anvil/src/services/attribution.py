"""Failure attribution service — heuristic-based credit assignment.

When a session has multiple skill invocations and some fail, this service
assigns blame scores to identify the most likely root cause. Uses three
heuristic rules (no LLM needed):

1. First-failure: first failed skill in session → base score 0.6
2. Repeated-failure: same skill fails multiple times → +0.2
3. Low-utility: skill with utility < 0.5 → +0.1

Scores are normalized so they sum to 1.0 within a session.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("anvil.attribution")


class AttributionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def attribute_session(self, session_id: str) -> list[dict[str, Any]]:
        """Compute failure attribution for all failed invocations in a session.

        Returns list of {invocation_id, skill_name, attribution_score, reason}.
        """
        # Get all invocations in this session, ordered by timestamp
        result = await self.db.execute(
            text("""
                SELECT id, skill_name, success, error_message, timestamp
                FROM anvil.invocations
                WHERE session_id = :sid AND category = 'skill'
                ORDER BY timestamp ASC
            """),
            {"sid": session_id},
        )
        rows = result.all()

        if not rows:
            return []

        # Filter to failed invocations
        failed = [r for r in rows if not r.success]
        if not failed:
            return []

        # Count failures per skill
        fail_counts: dict[str, int] = {}
        for r in failed:
            fail_counts[r.skill_name] = fail_counts.get(r.skill_name, 0) + 1

        # Get utility scores for failed skills
        skill_names = list(fail_counts.keys())
        placeholders = ", ".join(f":s{i}" for i in range(len(skill_names)))
        params = {f"s{i}": name for i, name in enumerate(skill_names)}
        utility_result = await self.db.execute(
            text(f"""
                SELECT name, utility_score
                FROM anvil.skills
                WHERE name IN ({placeholders})
            """),
            params,
        )
        utilities = {r.name: r.utility_score for r in utility_result.all()}

        # Compute raw scores
        first_failed_skill = failed[0].skill_name
        raw_scores: dict[str, dict] = {}

        for inv in failed:
            name = inv.skill_name
            if name not in raw_scores:
                score = 0.0
                reasons = []

                # Heuristic 1: First failure
                if name == first_failed_skill:
                    score += 0.6
                    reasons.append("first failure in session")

                # Heuristic 2: Repeated failure
                if fail_counts[name] > 1:
                    score += 0.2
                    reasons.append(f"failed {fail_counts[name]}x")

                # Heuristic 3: Low utility
                util = utilities.get(name)
                if util is not None and util < 0.5:
                    score += 0.1
                    reasons.append(f"low utility ({util:.2f})")

                # Minimum score for any failed skill
                if score == 0.0:
                    score = 0.1
                    reasons.append("failed in session")

                raw_scores[name] = {
                    "score": score,
                    "reason": "; ".join(reasons),
                }

        # Normalize scores to sum to 1.0
        total = sum(s["score"] for s in raw_scores.values())
        if total > 0:
            for s in raw_scores.values():
                s["score"] = round(s["score"] / total, 4)

        # Write attribution back to invocations
        attributions = []
        for inv in failed:
            name = inv.skill_name
            attr = raw_scores.get(name, {"score": 0.0, "reason": ""})
            await self.db.execute(
                text("""
                    UPDATE anvil.invocations
                    SET attribution_score = :score,
                        attribution_reason = :reason
                    WHERE id = :id
                """),
                {
                    "score": attr["score"],
                    "reason": attr["reason"],
                    "id": inv.id,
                },
            )
            attributions.append(
                {
                    "invocation_id": inv.id,
                    "skill_name": name,
                    "attribution_score": attr["score"],
                    "attribution_reason": attr["reason"],
                }
            )

        await self.db.commit()
        logger.info(
            "Attributed %d failures in session %s",
            len(attributions),
            session_id[:8],
        )
        return attributions

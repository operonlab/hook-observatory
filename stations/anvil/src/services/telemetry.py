"""Telemetry aggregation service for invocation stats."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("anvil.telemetry")


class TelemetryService:
    """Aggregation queries for invocation statistics."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_global_stats(self) -> dict[str, Any]:
        """Aggregated stats: total invocations, total skills, avg success rate,
        top skills by count, and 7-day trend.
        """
        # Total invocations + avg success rate
        summary = await self.db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_invocations,
                    ROUND(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) * 100, 2) AS avg_success_rate
                FROM anvil.invocations
            """)
        )
        summary_row = summary.one()
        total_invocations = summary_row.total_invocations or 0
        avg_success_rate = float(summary_row.avg_success_rate or 0)

        # Total active skills
        skills_result = await self.db.execute(
            text("SELECT COUNT(*) AS cnt FROM anvil.skills WHERE status = 'active'")
        )
        total_skills = skills_result.scalar() or 0

        # Top skills by invocation count (top 10)
        top_result = await self.db.execute(
            text("""
                SELECT
                    skill_name,
                    COUNT(*) AS count,
                    ROUND(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) * 100, 2) AS success_rate
                FROM anvil.invocations
                GROUP BY skill_name
                ORDER BY count DESC
                LIMIT 10
            """)
        )
        top_skills = [
            {
                "skill_name": r.skill_name,
                "count": r.count,
                "success_rate": float(r.success_rate or 0),
            }
            for r in top_result.all()
        ]

        # 7-day trend (daily counts)
        trend_result = await self.db.execute(
            text("""
                SELECT
                    date_trunc('day', timestamp)::date AS day,
                    COUNT(*) AS count
                FROM anvil.invocations
                WHERE timestamp > now() - interval '7 days'
                GROUP BY day
                ORDER BY day
            """)
        )
        trend_7d = [{"day": str(r.day), "count": r.count} for r in trend_result.all()]

        return {
            "total_invocations": total_invocations,
            "total_skills": total_skills,
            "avg_success_rate": avg_success_rate,
            "top_skills": top_skills,
            "trend_7d": trend_7d,
        }

    async def get_skill_stats(self, skill_name: str) -> dict[str, Any] | None:
        """Per-skill stats: daily counts, avg duration, failure rate, common errors."""
        # Check if any invocations exist
        exists_result = await self.db.execute(
            text("SELECT COUNT(*) FROM anvil.invocations WHERE skill_name = :name"),
            {"name": skill_name},
        )
        total = exists_result.scalar() or 0
        if total == 0:
            return None

        # Aggregated metrics
        metrics = await self.db.execute(
            text("""
                SELECT
                    COUNT(*) AS total_invocations,
                    ROUND(AVG(duration_ms)::numeric, 2) AS avg_duration_ms,
                    ROUND(AVG(CASE WHEN NOT success THEN 1.0 ELSE 0.0 END) * 100, 2) AS failure_rate
                FROM anvil.invocations
                WHERE skill_name = :name
            """),
            {"name": skill_name},
        )
        m = metrics.one()

        # Daily counts (last 30 days)
        daily_result = await self.db.execute(
            text("""
                SELECT
                    date_trunc('day', timestamp)::date AS day,
                    COUNT(*) AS count
                FROM anvil.invocations
                WHERE skill_name = :name
                    AND timestamp > now() - interval '30 days'
                GROUP BY day
                ORDER BY day
            """),
            {"name": skill_name},
        )
        daily_counts = [{"day": str(r.day), "count": r.count} for r in daily_result.all()]

        # Common errors (top 5)
        errors_result = await self.db.execute(
            text("""
                SELECT error_message, COUNT(*) AS count
                FROM anvil.invocations
                WHERE skill_name = :name
                    AND NOT success
                    AND error_message IS NOT NULL
                GROUP BY error_message
                ORDER BY count DESC
                LIMIT 5
            """),
            {"name": skill_name},
        )
        common_errors = [
            {"error_message": r.error_message, "count": r.count} for r in errors_result.all()
        ]

        return {
            "skill_name": skill_name,
            "total_invocations": m.total_invocations,
            "avg_duration_ms": float(m.avg_duration_ms) if m.avg_duration_ms else None,
            "failure_rate": float(m.failure_rate or 0),
            "daily_counts": daily_counts,
            "common_errors": common_errors,
        }

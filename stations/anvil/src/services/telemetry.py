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

    async def get_global_stats(self, category: str = "skill") -> dict[str, Any]:
        """Aggregated stats: total invocations, total skills, avg success rate,
        top skills by count, and 7-day trend.

        Pass category='all' to include all categories.
        """
        cat_filter = "" if category == "all" else "WHERE category = :category"
        cat_filter_and = "" if category == "all" else "AND category = :category"
        params: dict[str, str] = {} if category == "all" else {"category": category}

        # Total invocations + avg success rate
        summary = await self.db.execute(
            text(f"""
                SELECT
                    COUNT(*) AS total_invocations,
                    ROUND(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) * 100, 2) AS avg_success_rate
                FROM anvil.invocations
                {cat_filter}
            """),
            params,
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
            text(f"""
                SELECT
                    skill_name,
                    COUNT(*) AS count,
                    ROUND(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) * 100, 2) AS success_rate
                FROM anvil.invocations
                {cat_filter}
                GROUP BY skill_name
                ORDER BY count DESC
                LIMIT 10
            """),
            params,
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
            text(f"""
                SELECT
                    date_trunc('day', timestamp)::date AS day,
                    COUNT(*) AS count
                FROM anvil.invocations
                WHERE timestamp > now() - interval '7 days'
                {cat_filter_and}
                GROUP BY day
                ORDER BY day
            """),
            params,
        )
        trend_7d = [{"day": str(r.day), "count": r.count} for r in trend_result.all()]

        return {
            "total_invocations": total_invocations,
            "total_skills": total_skills,
            "avg_success_rate": avg_success_rate,
            "top_skills": top_skills,
            "trend_7d": trend_7d,
        }

    async def get_skill_stats(
        self, skill_name: str, category: str = "skill"
    ) -> dict[str, Any] | None:
        """Per-skill stats: daily counts, avg duration, failure rate, common errors.

        Pass category='all' to include all categories.
        """
        cat_filter_and = "" if category == "all" else "AND category = :category"
        params: dict[str, str] = (
            {"name": skill_name}
            if category == "all"
            else {"name": skill_name, "category": category}
        )

        # Check if any invocations exist
        exists_result = await self.db.execute(
            text(
                f"SELECT COUNT(*) FROM anvil.invocations WHERE skill_name = :name {cat_filter_and}"
            ),
            params,
        )
        total = exists_result.scalar() or 0
        if total == 0:
            return None

        # Aggregated metrics
        metrics = await self.db.execute(
            text(f"""
                SELECT
                    COUNT(*) AS total_invocations,
                    ROUND(AVG(duration_ms)::numeric, 2) AS avg_duration_ms,
                    ROUND(AVG(CASE WHEN NOT success THEN 1.0 ELSE 0.0 END) * 100, 2) AS failure_rate
                FROM anvil.invocations
                WHERE skill_name = :name
                {cat_filter_and}
            """),
            params,
        )
        m = metrics.one()

        # Daily counts (last 30 days)
        daily_result = await self.db.execute(
            text(f"""
                SELECT
                    date_trunc('day', timestamp)::date AS day,
                    COUNT(*) AS count
                FROM anvil.invocations
                WHERE skill_name = :name
                    AND timestamp > now() - interval '30 days'
                    {cat_filter_and}
                GROUP BY day
                ORDER BY day
            """),
            params,
        )
        daily_counts = [{"day": str(r.day), "count": r.count} for r in daily_result.all()]

        # Common errors (top 5)
        errors_result = await self.db.execute(
            text(f"""
                SELECT error_message, COUNT(*) AS count
                FROM anvil.invocations
                WHERE skill_name = :name
                    AND NOT success
                    AND error_message IS NOT NULL
                    {cat_filter_and}
                GROUP BY error_message
                ORDER BY count DESC
                LIMIT 5
            """),
            params,
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

    async def get_time_saved_stats(self, period: str = "30d") -> dict[str, Any]:
        """ROI stats: total/avg time saved across invocations with manual estimates."""
        period = period.strip().lower()
        if period.endswith("d") and period[:-1].isdigit():
            days = int(period[:-1])
        else:
            days = 30

        summary = await self.db.execute(
            text("""
                SELECT
                    COUNT(*) AS tasks_with_estimates,
                    COALESCE(SUM(time_saved_minutes), 0) AS total_saved_minutes,
                    AVG(time_saved_minutes) AS avg_saved_per_task
                FROM anvil.invocations
                WHERE manual_estimate_minutes IS NOT NULL
                    AND timestamp > now() - make_interval(days => :days)
            """),
            {"days": days},
        )
        row = summary.one()

        monthly_result = await self.db.execute(
            text("""
                SELECT
                    to_char(date_trunc('month', timestamp), 'YYYY-MM') AS month,
                    COALESCE(SUM(time_saved_minutes), 0) AS total_saved_minutes,
                    COUNT(*) AS tasks_count
                FROM anvil.invocations
                WHERE manual_estimate_minutes IS NOT NULL
                    AND timestamp > now() - make_interval(days => :days)
                GROUP BY date_trunc('month', timestamp)
                ORDER BY date_trunc('month', timestamp)
            """),
            {"days": days},
        )
        monthly_breakdown = [
            {
                "month": r.month,
                "total_saved_minutes": float(r.total_saved_minutes or 0),
                "tasks_count": r.tasks_count,
            }
            for r in monthly_result.all()
        ]

        return {
            "total_saved_minutes": float(row.total_saved_minutes or 0),
            "avg_saved_per_task": float(row.avg_saved_per_task) if row.avg_saved_per_task else None,
            "tasks_with_estimates": row.tasks_with_estimates or 0,
            "monthly_breakdown": monthly_breakdown,
        }

    async def compute_utility(self, skill_name: str, window_days: int = 90) -> dict[str, Any]:
        """Compute Memento-style utility score: U(s) = n_succ / (n_succ + n_fail).

        Returns dict with skill_name, n_succ, n_fail, utility_score, total_invocations.
        """
        result = await self.db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE success) AS n_succ,
                    COUNT(*) FILTER (WHERE NOT success) AS n_fail
                FROM anvil.invocations
                WHERE skill_name = :name
                    AND timestamp > now() - make_interval(days => :days)
            """),
            {"name": skill_name, "days": window_days},
        )
        row = result.one()
        n_succ = row.n_succ or 0
        n_fail = row.n_fail or 0
        total = n_succ + n_fail
        utility = round(n_succ / total, 4) if total > 0 else None
        return {
            "skill_name": skill_name,
            "n_succ": n_succ,
            "n_fail": n_fail,
            "utility_score": utility,
            "total_invocations": total,
        }

    async def get_all_utilities(
        self,
        threshold: float = 0.7,
        min_invocations: int = 5,
        window_days: int = 90,
    ) -> dict[str, Any]:
        """Get utility scores for all skills, flagging those below threshold."""
        result = await self.db.execute(
            text("""
                SELECT
                    skill_name,
                    COUNT(*) FILTER (WHERE success) AS n_succ,
                    COUNT(*) FILTER (WHERE NOT success) AS n_fail,
                    COUNT(*) AS total
                FROM anvil.invocations
                WHERE timestamp > now() - make_interval(days => :days)
                    AND category = 'skill'
                GROUP BY skill_name
                HAVING COUNT(*) >= :min_inv
                ORDER BY CASE WHEN COUNT(*) > 0
                    THEN COUNT(*) FILTER (WHERE success)::float / COUNT(*)
                    ELSE 0 END ASC
            """),
            {"days": window_days, "min_inv": min_invocations},
        )
        items = []
        flagged = []
        for r in result.all():
            total = r.total
            utility = round(r.n_succ / total, 4) if total > 0 else None
            below = utility is not None and utility < threshold
            items.append(
                {
                    "skill_name": r.skill_name,
                    "utility_score": utility,
                    "n_succ": r.n_succ,
                    "n_fail": r.n_fail,
                    "total_invocations": total,
                    "below_threshold": below,
                }
            )
            if below:
                flagged.append(r.skill_name)
        return {
            "items": items,
            "threshold": threshold,
            "flagged": flagged,
        }

    async def refresh_all_utilities(self, window_days: int = 90) -> int:
        """Batch-compute utility for all skills and cache in skills table.

        Returns number of skills updated.
        """
        result = await self.db.execute(
            text("""
                UPDATE anvil.skills s SET
                    utility_score = sub.utility,
                    utility_n_succ = sub.n_succ,
                    utility_n_fail = sub.n_fail,
                    utility_updated_at = now()
                FROM (
                    SELECT skill_name,
                        COUNT(*) FILTER (WHERE success) AS n_succ,
                        COUNT(*) FILTER (WHERE NOT success) AS n_fail,
                        CASE WHEN COUNT(*) > 0
                            THEN COUNT(*) FILTER (WHERE success)::float / COUNT(*)
                            ELSE NULL END AS utility
                    FROM anvil.invocations
                    WHERE timestamp > now() - make_interval(days => :days)
                    GROUP BY skill_name
                ) sub
                WHERE s.name = sub.skill_name
            """),
            {"days": window_days},
        )
        updated = result.rowcount or 0
        logger.info("Refreshed utility scores for %d skills (window=%dd)", updated, window_days)
        return updated

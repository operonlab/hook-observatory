"""AnvilGRCAdapter — Reflect-only G-R-C adapter for skill success rate monitoring.

Implements SupportsReflect to analyze invocation success rates, duration trends,
and per-skill degradation over the past 30 days.

This adapter is station-local: it reads directly from the anvil PostgreSQL schema
via SQLAlchemy async. No core module imports.

Usage (from runner script):
    adapter = AnvilGRCAdapter()
    items = await adapter.fetch_blocks(db)
    items_gen = adapter.gather_items(scope_id="global", blocks=items)
    result = adapter.reflect(items_gen, scope_id="global")
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# grc.py lives in core/src/shared/ but is pure Python (no ORM, no FastAPI).
# The runner adds core/src to sys.path, so this import works at runtime.
from src.shared.grc import GenerateItem, ReflectResult  # type: ignore[import]

LOOKBACK_DAYS = 30
TREND_WINDOW_DAYS = 7
MIN_INVOCATIONS_FOR_TREND = 3
DEGRADATION_DROP_THRESHOLD = 0.10  # 10 percentage point drop = degrading


class AnvilGRCAdapter:
    """Reflect-only adapter — monitors skill invocation success rates.

    Phase 1: Reflect only (no Curate, no Generate).
    Implements SupportsReflect Protocol from src.shared.grc.

    fetch_blocks() is async and must be awaited before gather_items().
    """

    # ── Async pre-fetch ────────────────────────────────────────────────

    async def fetch_blocks(
        self, db: AsyncSession, scope_id: str = "global"
    ) -> list[dict[str, Any]]:
        """Fetch invocations from the past LOOKBACK_DAYS from anvil schema.

        Returns list of dicts with keys:
          id, skill_name, success, duration_ms, error_message, timestamp
        """
        cutoff = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)

        result = await db.execute(
            text("""
                SELECT
                    id::text,
                    skill_name,
                    success,
                    duration_ms,
                    error_message,
                    timestamp
                FROM anvil.invocations
                WHERE timestamp >= :cutoff
                    AND category = 'skill'
                ORDER BY timestamp DESC
            """),
            {"cutoff": cutoff},
        )
        rows = result.mappings().all()

        return [
            {
                "id": r["id"],
                "skill_name": r["skill_name"],
                "success": r["success"],
                "duration_ms": r["duration_ms"],
                "error_message": r["error_message"],
                "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
            }
            for r in rows
        ]

    # ── SupportsReflect ────────────────────────────────────────────────

    def gather_items(self, scope_id: str, **kwargs: Any) -> list[GenerateItem]:
        """Convert pre-fetched blocks into GenerateItems.

        Caller MUST pass blocks=list[dict] via kwargs (pre-fetched by fetch_blocks()).
        If blocks is absent, returns empty list — no DB access here.
        """
        blocks: list[dict[str, Any]] = kwargs.get("blocks", [])
        return [
            GenerateItem(
                id=b["id"],
                content=b.get("skill_name", ""),
                metadata={
                    "skill_name": b.get("skill_name", "unknown"),
                    "success": b.get("success", True),
                    "duration_ms": b.get("duration_ms"),
                    "error_message": b.get("error_message"),
                    "timestamp": b.get("timestamp"),
                },
            )
            for b in blocks
        ]

    def reflect(self, items: list[GenerateItem], scope_id: str) -> ReflectResult:
        """Compute skill success rate metrics and detect degradation trends.

        Metrics written to result.metrics (all float for dataclass compat):
          - total_invocations
          - overall_success_rate  (0.0-1.0)
          - degrading_skill_count

        result.metrics also embeds by_skill as flat keys:
          - skill_{name}_count
          - skill_{name}_success_rate
          - skill_{name}_avg_duration_ms
        """
        result = ReflectResult(
            module="anvil",
            scope_id=scope_id,
            items_analyzed=len(items),
        )

        if not items:
            result.insights.append("No skill invocations in the last 30 days.")
            return result

        # ── Aggregate by skill ────────────────────────────────────────
        by_skill: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "success_count": 0, "durations": []}
        )
        now = datetime.now(UTC)
        cutoff_7d = now - timedelta(days=TREND_WINDOW_DAYS)
        by_skill_7d: dict[str, dict[str, int]] = defaultdict(
            lambda: {"count": 0, "success_count": 0}
        )
        by_skill_prior: dict[str, dict[str, int]] = defaultdict(
            lambda: {"count": 0, "success_count": 0}
        )

        total_success = 0
        for item in items:
            m = item.metadata
            skill = m.get("skill_name", "unknown")
            success = bool(m.get("success", True))
            duration = m.get("duration_ms")

            by_skill[skill]["count"] += 1
            if success:
                by_skill[skill]["success_count"] += 1
                total_success += 1
            if duration is not None:
                by_skill[skill]["durations"].append(int(duration))

            # Split into 7d window vs prior period for trend
            ts_raw = m.get("timestamp")
            if ts_raw:
                try:
                    ts = datetime.fromisoformat(ts_raw)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=UTC)
                    if ts >= cutoff_7d:
                        by_skill_7d[skill]["count"] += 1
                        if success:
                            by_skill_7d[skill]["success_count"] += 1
                    else:
                        by_skill_prior[skill]["count"] += 1
                        if success:
                            by_skill_prior[skill]["success_count"] += 1
                except ValueError:
                    pass

        total = len(items)
        overall_sr = total_success / total if total > 0 else 0.0

        # ── Build skill-level stats ───────────────────────────────────
        skill_stats: dict[str, dict[str, Any]] = {}
        for skill, data in by_skill.items():
            count = data["count"]
            sr = data["success_count"] / count if count > 0 else 0.0
            durations = data["durations"]
            avg_dur = sum(durations) / len(durations) if durations else None
            skill_stats[skill] = {
                "count": count,
                "success_rate": round(sr, 3),
                "avg_duration_ms": round(avg_dur, 1) if avg_dur is not None else None,
            }

        # ── Detect degrading skills ───────────────────────────────────
        degrading_skills: list[str] = []
        for skill in by_skill:
            recent = by_skill_7d[skill]
            prior = by_skill_prior[skill]
            if recent["count"] < MIN_INVOCATIONS_FOR_TREND:
                continue
            if prior["count"] < MIN_INVOCATIONS_FOR_TREND:
                continue
            recent_sr = recent["success_count"] / recent["count"]
            prior_sr = prior["success_count"] / prior["count"]
            if (prior_sr - recent_sr) >= DEGRADATION_DROP_THRESHOLD:
                degrading_skills.append(skill)
                result.anomalies.append(
                    f"skill {skill!r} success rate dropped from "
                    f"{prior_sr * 100:.0f}% to {recent_sr * 100:.0f}% in 7 days"
                )

        # ── Populate metrics ──────────────────────────────────────────
        result.metrics = {
            "total_invocations": float(total),
            "overall_success_rate": round(overall_sr, 3),
            "degrading_skill_count": float(len(degrading_skills)),
        }
        for skill, stats in skill_stats.items():
            safe = skill.replace("-", "_").replace("/", "_")
            result.metrics[f"skill_{safe}_count"] = float(stats["count"])
            result.metrics[f"skill_{safe}_success_rate"] = stats["success_rate"]
            if stats["avg_duration_ms"] is not None:
                result.metrics[f"skill_{safe}_avg_duration_ms"] = stats["avg_duration_ms"]

        # ── Insights ──────────────────────────────────────────────────
        # Top 3 skills by count
        top3 = sorted(skill_stats.items(), key=lambda x: -x[1]["count"])[:3]
        top3_str = ", ".join(f"{name} ({stats['success_rate'] * 100:.0f}%)" for name, stats in top3)
        result.insights.append(
            f"top 3 skills: {top3_str}" if top3_str else "no skill invocations in period"
        )
        result.insights.append(
            f"overall success rate: {overall_sr * 100:.1f}% "
            f"({total_success}/{total} invocations, last {LOOKBACK_DAYS}d)"
        )
        if degrading_skills:
            result.insights.append(
                f"{len(degrading_skills)} skill(s) degrading: " + ", ".join(degrading_skills)
            )
        else:
            result.insights.append("no degrading skills detected (7d trend stable)")

        return result

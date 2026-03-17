"""TaskflowGRCAdapter — Reflect-only G-R-C adapter for estimation accuracy analysis.

Implements SupportsReflect to analyze the gap between estimated_hours and
actual_hours for completed tasks over the past 90 days.

gather_items() is sync per the Protocol definition. The route layer calls
adapter.fetch_blocks(db, space_id) first (awaited), then passes the result as
blocks= kwarg to gather_items(). grc_routes.py detects fetch_blocks via hasattr().
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.grc import GenerateItem, ReflectResult

LOOKBACK_DAYS = 90
HIGH_ERROR_THRESHOLD = 1.0  # 100% error → anomaly

COMPLETED_STATUSES = {"done", "completed"}


class TaskflowGRCAdapter:
    """Reflect-only adapter — monitors task estimation accuracy.

    Phase 1: Reflect only (no Curate).
    Implements SupportsReflect Protocol from src.shared.grc.

    The fetch_blocks() async method is called by grc_routes.py before
    gather_items() to pre-fetch DB data in an async context.
    """

    # ── Async pre-fetch hook (detected by grc_routes via hasattr) ─────

    async def fetch_blocks(self, db: AsyncSession, space_id: str) -> list[dict[str, Any]]:
        """Fetch completed tasks with both estimated and actual hours (last 90 days).

        Returns list of dicts with keys:
          id, title, status, priority, estimated_hours, actual_hours, created_at.
        Only tasks with both hours fields populated are returned.
        """
        from src.modules.taskflow.models import Task

        cutoff = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)

        stmt = select(Task).where(
            Task.space_id == space_id,
            Task.status.in_(COMPLETED_STATUSES),
            Task.estimated_hours.is_not(None),
            Task.actual_hours.is_not(None),
            Task.created_at >= cutoff,
            Task.deleted_at.is_(None),
        )
        rows = list((await db.execute(stmt)).scalars().all())

        return [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "estimated_hours": t.estimated_hours,
                "actual_hours": t.actual_hours,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in rows
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
                content=b.get("title", ""),
                metadata={
                    "estimated_hours": b.get("estimated_hours", 0.0),
                    "actual_hours": b.get("actual_hours", 0.0),
                    "priority": b.get("priority", "medium"),
                    "status": b.get("status", "done"),
                    "created_at": b.get("created_at"),
                },
            )
            for b in blocks
        ]

    def reflect(self, items: list[GenerateItem], scope_id: str) -> ReflectResult:
        """Compute estimation accuracy metrics from completed tasks.

        Metrics written to result.metrics:
          - total_completed: number of completed tasks analyzed
          - avg_estimation_error: mean abs(estimated - actual) / estimated
          - overestimate_pct: % tasks where actual < estimated
          - underestimate_pct: % tasks where actual > estimated
          - by_priority_{p}_avg_error: avg error rate per priority level
        """
        result = ReflectResult(
            module="taskflow",
            scope_id=scope_id,
            items_analyzed=len(items),
        )

        if not items:
            result.insights.append(
                f"No completed tasks with hour estimates in the last {LOOKBACK_DAYS} days."
            )
            return result

        # ── Core metrics ──────────────────────────────────────────────
        errors: list[float] = []
        over_count = 0
        under_count = 0
        exact_count = 0

        by_priority: dict[str, list[float]] = defaultdict(list)

        for it in items:
            est = it.metadata.get("estimated_hours", 0.0) or 0.0
            act = it.metadata.get("actual_hours", 0.0) or 0.0
            priority = it.metadata.get("priority", "medium")

            if est <= 0:
                continue  # skip tasks with zero estimate — avoid division by zero

            error_rate = abs(est - act) / est
            errors.append(error_rate)
            by_priority[priority].append(error_rate)

            if act < est:
                over_count += 1
            elif act > est:
                under_count += 1
            else:
                exact_count += 1

        valid_count = len(errors)
        if valid_count == 0:
            result.insights.append(
                "All completed tasks have zero estimated hours — cannot compute error rates."
            )
            return result

        avg_error = sum(errors) / valid_count
        overestimate_pct = over_count / valid_count * 100
        underestimate_pct = under_count / valid_count * 100

        # Per-priority average error
        priority_metrics: dict[str, float] = {
            priority: round(sum(vals) / len(vals), 3) for priority, vals in by_priority.items()
        }

        # ── Populate result ───────────────────────────────────────────
        result.metrics = {
            "total_completed": float(len(items)),
            "avg_estimation_error": round(avg_error, 3),
            "overestimate_pct": round(overestimate_pct, 1),
            "underestimate_pct": round(underestimate_pct, 1),
            **{f"by_priority_{p}_avg_error": v for p, v in priority_metrics.items()},
        }

        # ── Insights ──────────────────────────────────────────────────
        result.insights.append(
            f"Average estimation error: {avg_error * 100:.0f}% "
            f"({len(items)} completed tasks, last {LOOKBACK_DAYS}d)"
        )

        if overestimate_pct > underestimate_pct:
            result.insights.append(
                f"Tasks tend to be overestimated: {overestimate_pct:.0f}%"
                " finished faster than planned"
            )
        else:
            result.insights.append(
                f"Tasks tend to be underestimated: {underestimate_pct:.0f}%"
                " took longer than planned"
            )

        for priority, avg in priority_metrics.items():
            if avg > 0.3:
                direction = (
                    "underestimated"
                    if by_priority[priority]
                    and (
                        sum(
                            1
                            for it in items
                            if it.metadata.get("priority") == priority
                            and (it.metadata.get("actual_hours") or 0)
                            > (it.metadata.get("estimated_hours") or 0)
                        )
                        > len(by_priority[priority]) / 2
                    )
                    else "overestimated"
                )
                result.insights.append(
                    f"{priority.capitalize()} tasks {direction} by {avg * 100:.0f}% on average"
                )

        # ── Anomalies: tasks with > 100% estimation error ─────────────
        for it in items:
            est = it.metadata.get("estimated_hours", 0.0) or 0.0
            act = it.metadata.get("actual_hours", 0.0) or 0.0
            if est <= 0:
                continue
            error_rate = abs(est - act) / est
            if error_rate > HIGH_ERROR_THRESHOLD:
                result.anomalies.append(
                    f"Task '{it.content}' ({it.id[:8]}): "
                    f"estimated {est:.1f}h, actual {act:.1f}h "
                    f"({error_rate * 100:.0f}% error)"
                )

        return result

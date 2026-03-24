"""CaptureGRCAdapter — Reflect-only G-R-C adapter for enrichment quality monitoring.

Implements SupportsReflect to analyze enrichment confidence, status distribution,
and per-adapter quality trends over the past 7 days.

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

LOOKBACK_DAYS = 7


def _low_confidence_threshold(enrichment_count: int = 0) -> float:
    """Dynamic threshold for flagging low-confidence captures.

    Captures that have been enriched multiple times have had more chances
    to improve quality, so the bar rises slightly. Clamped to [0.35, 0.65].
    """
    return max(0.35, min(0.65, 0.45 + 0.04 * enrichment_count))


# Module-level constant kept for backward-compatible metric labels and log messages.
# Use _low_confidence_threshold() for per-item gating.
LOW_CONFIDENCE_THRESHOLD = 0.5


class CaptureGRCAdapter:
    """Reflect-only adapter — monitors enrichment pipeline quality.

    Phase 1: Reflect only (no Curate).
    Implements SupportsReflect Protocol from src.shared.grc.

    The fetch_blocks() async method is called by grc_routes.py before
    gather_items() to pre-fetch DB data in an async context.
    """

    # ── Async pre-fetch hook (detected by grc_routes via hasattr) ─────

    async def fetch_blocks(self, db: AsyncSession, space_id: str) -> list[dict[str, Any]]:
        """Fetch recent captures + enrichment counts for this space (last 7 days).

        Returns list of dicts with keys:
          id, raw_input, status, completeness, adapter_name,
          enrichment_count, created_at.
        """
        from src.modules.capture.models import Capture, CaptureEnrichment

        cutoff = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)

        stmt = select(Capture).where(
            Capture.space_id == space_id,
            Capture.created_at >= cutoff,
            Capture.deleted_at.is_(None),
        )
        rows = list((await db.execute(stmt)).scalars().all())
        if not rows:
            return []

        capture_ids = [r.id for r in rows]

        # Count enrichments per capture
        enrich_stmt = select(CaptureEnrichment.capture_id).where(
            CaptureEnrichment.capture_id.in_(capture_ids)
        )
        enrich_rows = (await db.execute(enrich_stmt)).all()

        enrich_counts: dict[str, int] = defaultdict(int)
        for row in enrich_rows:
            enrich_counts[row.capture_id] += 1

        return [
            {
                "id": c.id,
                "raw_input": c.raw_input or "",
                "status": c.status,
                "completeness": c.completeness or 0.0,
                "adapter_name": c.module,
                "enrichment_count": enrich_counts[c.id],
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in rows
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
                content=b.get("raw_input", ""),
                metadata={
                    "confidence": b.get("completeness", 0.0),
                    "status": b.get("status", "pending"),
                    "enrichment_count": b.get("enrichment_count", 0),
                    "adapter_name": b.get("adapter_name", "unknown"),
                    "created_at": b.get("created_at"),
                },
            )
            for b in blocks
        ]

    def reflect(self, items: list[GenerateItem], scope_id: str) -> ReflectResult:
        """Compute enrichment quality metrics from captured items.

        Metrics written to result.metrics:
          - avg_confidence: mean completeness score
          - low_confidence_pct: % items below LOW_CONFIDENCE_THRESHOLD
          - needs_review_count: items with status='needs_review'
          - adapter_conf_{name}: avg confidence per module/adapter
        """
        result = ReflectResult(
            module="capture",
            scope_id=scope_id,
            items_analyzed=len(items),
        )

        if not items:
            result.insights.append("No captures in the last 7 days.")
            return result

        confidences = [it.metadata.get("confidence", 0.0) for it in items]
        avg_conf = sum(confidences) / len(confidences)
        low_conf_count = sum(1 for c in confidences if c < LOW_CONFIDENCE_THRESHOLD)
        low_conf_pct = low_conf_count / len(confidences) * 100

        # Status distribution
        by_status: dict[str, int] = defaultdict(int)
        for it in items:
            by_status[it.metadata.get("status", "unknown")] += 1
        needs_review_count = by_status.get("needs_review", 0)

        # Per-adapter average confidence
        adapter_conf: dict[str, list[float]] = defaultdict(list)
        for it in items:
            adapter_conf[it.metadata.get("adapter_name", "unknown")].append(
                it.metadata.get("confidence", 0.0)
            )
        by_adapter = {name: round(sum(vals) / len(vals), 3) for name, vals in adapter_conf.items()}

        # Populate metrics
        result.metrics = {
            "avg_confidence": round(avg_conf, 3),
            "low_confidence_pct": round(low_conf_pct, 1),
            "needs_review_count": float(needs_review_count),
            **{f"adapter_conf_{name}": v for name, v in by_adapter.items()},
        }

        # Insights
        result.insights.append(
            f"Enrichment accuracy: {avg_conf * 100:.0f}% avg confidence "
            f"({len(items)} captures, last {LOOKBACK_DAYS}d)"
        )
        if low_conf_pct > 10:
            result.insights.append(
                f"Low confidence spike: {low_conf_pct:.0f}% items below "
                f"{LOW_CONFIDENCE_THRESHOLD} threshold"
            )
        else:
            result.insights.append(
                f"Enrichment quality stable: only {low_conf_pct:.0f}% low confidence"
            )
        if needs_review_count > 0:
            result.insights.append(f"{needs_review_count} capture(s) flagged for human review")
        status_parts = ", ".join(f"{s}={n}" for s, n in sorted(by_status.items()))
        result.insights.append(f"Status distribution: {status_parts}")

        # Anomaly detection: flag adapters with critically low confidence
        for name, avg in by_adapter.items():
            if avg < LOW_CONFIDENCE_THRESHOLD:
                result.anomalies.append(
                    f"Adapter '{name}' avg confidence low: {avg:.2f} "
                    f"(below {LOW_CONFIDENCE_THRESHOLD} threshold)"
                )

        return result

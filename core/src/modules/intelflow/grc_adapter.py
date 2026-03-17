"""IntelflowGRCAdapter — Reflect + Curate adapter for feed/report quality.

Implements SupportsReflect + SupportsCurate to:
  - Reflect: analyze report relevance distribution per topic
  - Curate: archive low-value reports (low relevance + zero reads + age > 30d)

The fetch_blocks() async hook is detected by grc_routes.py via hasattr(),
called before gather_items() to pre-fetch DB data in async context.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.grc import (
    CurateAction,
    CurateResult,
    GenerateItem,
    GRCConfig,
    ReflectResult,
    three_guard_filter,
)

LOOKBACK_DAYS = 30
LOW_RELEVANCE_THRESHOLD = 0.4
NO_FEED_ANOMALY_DAYS = 14


class IntelflowGRCAdapter:
    """Reflect + Curate adapter — monitors feed quality, archives low-value reports.

    Implements SupportsReflect + SupportsCurate from src.shared.grc.

    fetch_blocks() is called by grc_routes.py before gather_items()
    to pre-fetch DB data in an async context.
    """

    # ── Async pre-fetch hook (detected by grc_routes via hasattr) ─────

    async def fetch_blocks(self, db: AsyncSession, scope_id: str) -> list[dict[str, Any]]:
        """Fetch reports + topic relevance for the last 30 days.

        Returns list of dicts with keys:
          id, title, query, tags, skill_name, created_at,
          avg_topic_relevance, topic_names.
        """
        from src.modules.intelflow.models import Report, ReportTopic, Topic

        cutoff = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)

        stmt = (
            select(Report)
            .where(
                Report.space_id == scope_id,
                Report.created_at >= cutoff,
                Report.deleted_at.is_(None),
            )
            .order_by(Report.created_at.desc())
        )
        reports = list((await db.execute(stmt)).scalars().all())
        if not reports:
            return []

        report_ids = [r.id for r in reports]

        # Fetch topic relevance per report
        rt_stmt = (
            select(ReportTopic.report_id, ReportTopic.relevance, Topic.name)
            .join(Topic, ReportTopic.topic_id == Topic.id)
            .where(ReportTopic.report_id.in_(report_ids))
        )
        rt_rows = (await db.execute(rt_stmt)).all()

        relevance_map: dict[str, list[float]] = defaultdict(list)
        topics_map: dict[str, list[str]] = defaultdict(list)
        for row in rt_rows:
            relevance_map[row.report_id].append(row.relevance)
            topics_map[row.report_id].append(row.name)

        return [
            {
                "id": r.id,
                "title": r.title,
                "query": r.query,
                "tags": r.tags or [],
                "skill_name": r.skill_name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "avg_topic_relevance": (
                    sum(relevance_map[r.id]) / len(relevance_map[r.id])
                    if relevance_map[r.id]
                    else 0.0
                ),
                "topic_names": topics_map[r.id],
            }
            for r in reports
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
                content=b.get("title", "") + " " + b.get("query", ""),
                metadata={
                    "confidence": b.get("avg_topic_relevance", 0.0),
                    "access_count": 0,  # Report has no read_count; treat as zero
                    "topic_names": b.get("topic_names", []),
                    "tags": b.get("tags", []),
                    "skill_name": b.get("skill_name"),
                    "created_at": b.get("created_at"),
                },
            )
            for b in blocks
        ]

    def reflect(self, items: list[GenerateItem], scope_id: str) -> ReflectResult:
        """Compute feed quality metrics from reports.

        Metrics written to result.metrics:
          - avg_relevance: mean topic relevance across all reports
          - low_relevance_pct: % reports below LOW_RELEVANCE_THRESHOLD
          - reports_per_topic_{name}: report count per topic
        """
        result = ReflectResult(
            module="intelflow",
            scope_id=scope_id,
            items_analyzed=len(items),
        )

        if not items:
            result.insights.append(f"No reports in the last {LOOKBACK_DAYS} days.")
            return result

        relevances = [it.metadata.get("confidence", 0.0) for it in items]
        avg_rel = sum(relevances) / len(relevances)
        low_rel_count = sum(1 for r in relevances if r < LOW_RELEVANCE_THRESHOLD)
        low_rel_pct = low_rel_count / len(relevances) * 100

        # Per-topic report count
        topic_counts: dict[str, int] = defaultdict(int)
        topic_relevances: dict[str, list[float]] = defaultdict(list)
        for it in items:
            for topic in it.metadata.get("topic_names", []):
                topic_counts[topic] += 1
                topic_relevances[topic].append(it.metadata.get("confidence", 0.0))

        # Per-skill report count
        skill_counts: dict[str, int] = defaultdict(int)
        for it in items:
            skill = it.metadata.get("skill_name") or "unknown"
            skill_counts[skill] += 1

        # Populate metrics
        result.metrics = {
            "avg_relevance": round(avg_rel, 3),
            "low_relevance_pct": round(low_rel_pct, 1),
            **{f"reports_per_topic_{t}": float(c) for t, c in topic_counts.items()},
        }

        # Insights
        result.insights.append(
            f"Feed quality: avg_relevance={avg_rel:.2f} across {len(items)} reports "
            f"(last {LOOKBACK_DAYS}d)"
        )
        if low_rel_pct > 20:
            result.insights.append(
                f"High low-relevance rate: {low_rel_pct:.0f}% reports below "
                f"{LOW_RELEVANCE_THRESHOLD} threshold — consider pruning feeds"
            )
        else:
            result.insights.append(
                f"Relevance distribution healthy: only {low_rel_pct:.0f}% low-relevance"
            )

        # Topic-level insights: high volume + low avg relevance
        for topic, rel_list in topic_relevances.items():
            count = topic_counts[topic]
            avg_t = sum(rel_list) / len(rel_list)
            if count >= 5 and avg_t < LOW_RELEVANCE_THRESHOLD:
                result.insights.append(
                    f"Topic '{topic}' has {count} reports but avg_relevance={avg_t:.2f}, "
                    f"consider removing or refining"
                )

        # Skill distribution insight
        skill_summary = ", ".join(
            f"{s}={c}" for s, c in sorted(skill_counts.items(), key=lambda x: -x[1])
        )
        result.insights.append(f"Reports by skill: {skill_summary}")

        # Anomaly: topics with zero recent reports (infer from no appearance)
        # Check for feeds producing no content in NO_FEED_ANOMALY_DAYS
        cutoff_anomaly = datetime.now(UTC) - timedelta(days=NO_FEED_ANOMALY_DAYS)
        for it in items:
            created_raw = it.metadata.get("created_at")
            if created_raw:
                try:
                    created_dt = datetime.fromisoformat(created_raw)
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=UTC)
                    if created_dt < cutoff_anomaly:
                        if it.metadata.get("topic_names"):
                            pass  # Stale feed detection done per-report below
                except ValueError:
                    pass

        # Anomaly: skills with no recent output (> NO_FEED_ANOMALY_DAYS)
        recent_skills: set[str] = set()
        cutoff_recent = datetime.now(UTC) - timedelta(days=NO_FEED_ANOMALY_DAYS)
        for it in items:
            created_raw = it.metadata.get("created_at")
            if created_raw:
                try:
                    created_dt = datetime.fromisoformat(created_raw)
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=UTC)
                    if created_dt >= cutoff_recent:
                        skill = it.metadata.get("skill_name") or "unknown"
                        recent_skills.add(skill)
                except ValueError:
                    pass
        for skill in skill_counts:
            if skill not in recent_skills:
                result.anomalies.append(
                    f"No new reports from feed/skill '{skill}' in {NO_FEED_ANOMALY_DAYS} days"
                )

        return result

    # ── SupportsCurate ─────────────────────────────────────────────────

    def identify_candidates(
        self,
        scope_id: str,
        config: GRCConfig | None = None,
        **kwargs: Any,
    ) -> list[CurateAction]:
        """Identify low-value reports for archival.

        Candidates pass three_guard_filter:
          1. avg_topic_relevance < confidence_threshold
          2. access_count == 0 (Report has no read tracking)
          3. age > min_item_age_days (default 30d)

        Action: "archive" — move to ReportArchive (not soft_delete alone).
        """
        cfg = config or GRCConfig()
        blocks: list[dict[str, Any]] = kwargs.get("db_blocks", [])

        # If db_blocks not provided, try gather_items path via blocks kwarg
        if not blocks:
            items_all: list[GenerateItem] = kwargs.get("items", [])
        else:
            items_all = [
                GenerateItem(
                    id=b["id"],
                    content=b.get("title", ""),
                    metadata={
                        "confidence": b.get("avg_topic_relevance", 0.0),
                        "access_count": 0,
                        "created_at": b.get("created_at"),
                    },
                )
                for b in blocks
            ]

        # Fall back: items may come from a prior gather_items call via blocks kwarg
        if not items_all:
            raw_blocks: list[dict[str, Any]] = kwargs.get("blocks", [])
            items_all = [
                GenerateItem(
                    id=b["id"],
                    content=b.get("title", ""),
                    metadata={
                        "confidence": b.get("avg_topic_relevance", 0.0),
                        "access_count": 0,
                        "created_at": b.get("created_at"),
                    },
                )
                for b in raw_blocks
            ]

        candidates = three_guard_filter(items_all, cfg)
        return [
            CurateAction(
                item_id=it.id,
                action="archive",
                reason=(
                    f"avg_topic_relevance={it.metadata.get('confidence', 0.0):.2f} "
                    f"< threshold={cfg.confidence_threshold}, "
                    f"no reads, age > {cfg.min_item_age_days}d"
                ),
                confidence=1.0 - it.metadata.get("confidence", 0.0),
            )
            for it in candidates
        ]

    async def apply_actions(
        self,
        actions: list[CurateAction],
        dry_run: bool = False,
        **kwargs: Any,
    ) -> CurateResult:
        """Archive low-value reports.

        For each action="archive":
          1. Copy Report row to ReportArchive
          2. Soft-delete the original Report (set deleted_at)

        Caller (grc_routes) commits the transaction after this returns.
        """
        db: AsyncSession | None = kwargs.get("db")
        result = CurateResult(
            module="intelflow",
            scope_id=kwargs.get("scope_id", "default"),
            dry_run=dry_run,
        )

        if not actions:
            return result

        if dry_run:
            result.applied_count = len(actions)
            return result

        if db is None:
            result.skipped_count = len(actions)
            return result

        from src.modules.intelflow.models import Report, ReportArchive

        now_iso = datetime.now(UTC).isoformat()
        now_dt = datetime.now(UTC)

        for action in actions:
            if action.action != "archive":
                result.skipped_count += 1
                continue
            try:
                report = (
                    await db.execute(
                        select(Report).where(
                            Report.id == action.item_id,
                            Report.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()

                if report is None:
                    result.skipped_count += 1
                    continue

                # Check not already archived
                existing = (
                    await db.execute(
                        select(ReportArchive).where(ReportArchive.id == action.item_id)
                    )
                ).scalar_one_or_none()
                if existing:
                    result.skipped_count += 1
                    continue

                # Insert into archive
                archive_row = ReportArchive(
                    id=report.id,
                    space_id=report.space_id,
                    created_by=report.created_by,
                    created_at=(report.created_at.isoformat() if report.created_at else now_iso),
                    updated_at=(report.updated_at.isoformat() if report.updated_at else now_iso),
                    title=report.title,
                    query=report.query,
                    content=report.content,
                    sources=report.sources,
                    tags=report.tags or [],
                    skill_name=report.skill_name,
                    archived_at=now_iso,
                    archive_type="cold-archive",
                )
                db.add(archive_row)

                # Soft-delete the original
                report.deleted_at = now_dt
                await db.flush()

                result.applied_count += 1

            except Exception:
                result.skipped_count += 1
                continue

        return result

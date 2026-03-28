"""Intelflow services — CRUD + dashboard.

Standalone variant:
- No EventBus publish (no cross-module events)
- No @cached decorators (no Redis)
- No embedding generation (no Qdrant/oMLX)
- No RLM synthesis (no rlm_engine dependency)
- Same CRUD method signatures preserved for API compatibility
"""

import logging
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.schemas import PaginatedResponse, PaginationParams
from shared.services import BaseCRUDService

from .models import (
    Report,
    ReportTopic,
    SearchSession,
    Topic,
    TopicRelation,
)
from .schemas import (
    DashboardResponse,
    ReportBrief,
    ReportCreate,
    ReportResponse,
    ReportUpdate,
    TimelineEntry,
    TimelineResponse,
    TopicBrief,
    TopicCreate,
    TopicGraphEdge,
    TopicGraphNode,
    TopicGraphResponse,
    TopicResponse,
)

logger = logging.getLogger(__name__)

# ======================== Report Service ========================


class ReportService(BaseCRUDService[Report, ReportCreate, ReportUpdate, ReportResponse]):
    model = Report
    audit_module = "intelflow"
    audit_entity_type = "reports"

    def before_create(self, data: ReportCreate, **kwargs: Any) -> dict:
        return data.model_dump(exclude={"created_at"})

    def to_response(self, instance: Report) -> ReportResponse:
        topics = []
        if hasattr(instance, "topics") and instance.topics:
            topics = [
                TopicBrief(id=t.id, name=t.name, display_name=t.display_name)
                for t in instance.topics
            ]
        return ReportResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            title=instance.title,
            query=instance.query,
            content=instance.content,
            sources=instance.sources or [],
            tags=instance.tags or [],
            skill_name=instance.skill_name,
            topics=topics,
        )

    def to_brief(self, instance: Report) -> ReportBrief:
        return ReportBrief(
            id=instance.id,
            title=instance.title,
            query=instance.query,
            tags=instance.tags or [],
            skill_name=instance.skill_name,
            created_at=instance.created_at,
        )

    async def list_by_tags(
        self,
        db: AsyncSession,
        space_id: str,
        tags: list[str],
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[ReportResponse]:
        p = pagination or PaginationParams()
        base = select(Report).where(
            Report.space_id == space_id,
            Report.tags.contains(tags),
            Report.deleted_at == None,  # noqa: E711
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = (
            base.order_by(Report.created_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[ReportResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def list_by_topic(
        self,
        db: AsyncSession,
        space_id: str,
        topic_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[ReportResponse]:
        p = pagination or PaginationParams()
        base = (
            select(Report)
            .join(ReportTopic, Report.id == ReportTopic.report_id)
            .where(
                Report.space_id == space_id,
                ReportTopic.topic_id == topic_id,
                Report.deleted_at == None,  # noqa: E711
            )
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = (
            base.order_by(Report.created_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[ReportResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


# ======================== Topic Service ========================


class TopicService:
    """Topic CRUD + graph operations."""

    async def list_topics(
        self,
        db: AsyncSession,
        space_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[TopicResponse]:
        p = pagination or PaginationParams()
        count_q = select(func.count()).select_from(Topic).where(Topic.space_id == space_id)
        total = (await db.execute(count_q)).scalar_one()
        q = (
            select(Topic)
            .where(Topic.space_id == space_id)
            .order_by(Topic.report_count.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[TopicResponse](
            items=[self._to_response(t) for t in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def create_topic(
        self,
        db: AsyncSession,
        space_id: str,
        data: TopicCreate,
        user_id: str | None = None,
    ) -> TopicResponse:
        topic = Topic(
            space_id=space_id,
            created_by=user_id,
            name=data.name,
            display_name=data.display_name or data.name,
        )
        db.add(topic)
        await db.flush()
        return self._to_response(topic)

    async def get_or_create(
        self,
        db: AsyncSession,
        space_id: str,
        name: str,
    ) -> Topic:
        """Get existing topic or create if not found."""
        q = select(Topic).where(Topic.space_id == space_id, Topic.name == name)
        existing = (await db.execute(q)).scalar_one_or_none()
        if existing:
            return existing
        topic = Topic(space_id=space_id, name=name, display_name=name)
        db.add(topic)
        await db.flush()
        return topic

    async def get_graph(self, db: AsyncSession, space_id: str) -> TopicGraphResponse:
        """Return topic graph (nodes + edges) for visualization."""
        topics = (await db.execute(select(Topic).where(Topic.space_id == space_id))).scalars().all()

        relations = (
            (
                await db.execute(
                    select(TopicRelation)
                    .join(Topic, TopicRelation.source_topic_id == Topic.id)
                    .where(Topic.space_id == space_id)
                )
            )
            .scalars()
            .all()
        )

        nodes = [
            TopicGraphNode(
                id=t.id,
                name=t.name,
                display_name=t.display_name,
                report_count=t.report_count,
            )
            for t in topics
        ]
        edges = [
            TopicGraphEdge(
                source=r.source_topic_id,
                target=r.target_topic_id,
                weight=r.weight,
            )
            for r in relations
        ]
        return TopicGraphResponse(nodes=nodes, edges=edges)

    async def get_related(self, db: AsyncSession, topic_id: str) -> list[TopicResponse]:
        """Get topics related to a given topic."""
        q = (
            select(Topic)
            .join(TopicRelation, Topic.id == TopicRelation.target_topic_id)
            .where(TopicRelation.source_topic_id == topic_id)
            .order_by(TopicRelation.weight.desc())
        )
        rows = (await db.execute(q)).scalars().all()
        return [self._to_response(t) for t in rows]

    async def extract_from_report(
        self,
        db: AsyncSession,
        report: Report,
    ) -> list[Topic]:
        """Extract topics from a report's tags and create ReportTopic links.
        Skips the report's skill_name since that's metadata, not a topic."""
        if not report.tags:
            return []
        skip = {report.skill_name.strip().lower()} if report.skill_name else set()
        created_topics: list[Topic] = []
        for tag in report.tags:
            tag_clean = tag.strip().lower()
            if not tag_clean or tag_clean in skip:
                continue
            topic = await self.get_or_create(db, report.space_id, tag_clean)
            # Check if link already exists
            existing = (
                await db.execute(
                    select(ReportTopic).where(
                        ReportTopic.report_id == report.id,
                        ReportTopic.topic_id == topic.id,
                    )
                )
            ).scalar_one_or_none()
            if not existing:
                db.add(ReportTopic(report_id=report.id, topic_id=topic.id))
                topic.report_count = topic.report_count + 1
            created_topics.append(topic)
        await db.flush()
        return created_topics

    async def backfill_all(
        self,
        db: AsyncSession,
        space_id: str,
    ) -> dict[str, int]:
        """Backfill topics from all existing reports in a space.
        Clears existing topic data first to ensure clean state."""
        # Clear existing data
        await db.execute(delete(ReportTopic))
        await db.execute(delete(Topic).where(Topic.space_id == space_id))
        await db.flush()

        reports = (
            (await db.execute(select(Report).where(Report.space_id == space_id))).scalars().all()
        )
        total_links = 0
        for report in reports:
            topics = await self.extract_from_report(db, report)
            total_links += len(topics)
        await db.flush()
        return {"reports_processed": len(reports), "topic_links_created": total_links}

    async def sync_report_counts(self, db: AsyncSession, space_id: str) -> int:
        """Rebuild report_count for all topics in a space."""
        # Single GROUP BY query instead of N+1
        count_q = (
            select(ReportTopic.topic_id, func.count().label("cnt"))
            .join(Topic, ReportTopic.topic_id == Topic.id)
            .where(Topic.space_id == space_id)
            .group_by(ReportTopic.topic_id)
        )
        count_map = {row.topic_id: row.cnt for row in (await db.execute(count_q)).all()}

        topics = (await db.execute(select(Topic).where(Topic.space_id == space_id))).scalars().all()
        for topic in topics:
            topic.report_count = count_map.get(topic.id, 0)
        await db.flush()
        return len(topics)

    def _to_response(self, topic: Topic) -> TopicResponse:
        return TopicResponse(
            id=topic.id,
            space_id=topic.space_id,
            created_by=topic.created_by,
            created_at=topic.created_at,
            updated_at=topic.updated_at,
            name=topic.name,
            display_name=topic.display_name,
            report_count=topic.report_count,
        )


# ======================== SearchSession Service ========================


class SearchSessionService:
    """Track search queries and outcomes."""

    async def record(
        self,
        db: AsyncSession,
        space_id: str,
        query: str,
        source: str | None = None,
        result_type: str | None = None,
        report_id: str | None = None,
    ) -> SearchSession:
        session = SearchSession(
            space_id=space_id,
            query=query,
            source=source,
            result_type=result_type,
            report_id=report_id,
        )
        db.add(session)
        await db.flush()
        return session


# ======================== Dashboard Service ========================


class DashboardService:
    """Statistics and timeline data."""

    async def get_summary(self, db: AsyncSession, space_id: str) -> DashboardResponse:
        total_reports = (
            await db.execute(
                select(func.count()).select_from(Report).where(Report.space_id == space_id)
            )
        ).scalar_one()

        total_topics = (
            await db.execute(
                select(func.count()).select_from(Topic).where(Topic.space_id == space_id)
            )
        ).scalar_one()

        recent = (
            (
                await db.execute(
                    select(Report)
                    .where(Report.space_id == space_id)
                    .order_by(Report.created_at.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )

        return DashboardResponse(
            total_reports=total_reports,
            total_topics=total_topics,
            recent_reports=[
                ReportBrief(
                    id=r.id,
                    title=r.title,
                    query=r.query,
                    tags=r.tags or [],
                    skill_name=r.skill_name,
                    created_at=r.created_at,
                )
                for r in recent
            ],
        )

    async def get_timeline(
        self, db: AsyncSession, space_id: str, days: int = 30
    ) -> TimelineResponse:
        q = (
            select(
                func.date_trunc("day", Report.created_at).label("day"),
                func.count().label("cnt"),
            )
            .where(Report.space_id == space_id)
            .group_by("day")
            .order_by("day")
            .limit(days)
        )
        rows = (await db.execute(q)).all()
        return TimelineResponse(
            entries=[TimelineEntry(date=row.day.date(), count=row.cnt) for row in rows]
        )


# ======================== Module-level singletons ========================

report_service = ReportService()
topic_service = TopicService()
search_session_service = SearchSessionService()
dashboard_service = DashboardService()

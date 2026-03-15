"""Intelflow services — CRUD + semantic search + dashboard.

This is the PUBLIC API of the intelflow module.
Other modules import from here, never from models.py.
"""

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.events.types import IntelflowEvents
from src.shared.cache import cached
from src.shared.embedding import get_embedding
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService

from .models import (
    Report,
    ReportArchive,
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

# ======================== Report Service ========================


class ReportService(BaseCRUDService[Report, ReportCreate, ReportUpdate, ReportResponse]):
    model = Report
    audit_module = "intelflow"
    audit_entity_type = "reports"

    def before_create(self, data: ReportCreate, **kwargs: Any) -> dict:
        return data.model_dump(exclude={"created_at"})

    def after_create(self, instance: Report) -> None:
        event_bus.publish_fire_and_forget(
            Event(
                type=IntelflowEvents.REPORT_CREATED,
                data={
                    "id": instance.id,
                    "report_id": instance.id,  # backward compat
                    "space_id": instance.space_id,
                    "title": instance.title,
                    "query": instance.query,
                    "content": instance.content,
                    "tags": instance.tags or [],
                    "skill_name": instance.skill_name,
                    "created_at": instance.created_at.isoformat() if instance.created_at else None,
                    "updated_at": instance.updated_at.isoformat() if instance.updated_at else None,
                },
                source="intelflow",
                user_id=instance.created_by,
            )
        )

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

    async def get_with_content_resolve(self, db: AsyncSession, report_id: str) -> Report | None:
        """Get a report and resolve S3 content references transparently.

        For archived reports whose content was offloaded to RustFS (COLD-BLOB),
        this fetches the content from S3 and returns it in the content field.
        """
        instance = await self.get(db, report_id)
        if instance is None:
            # Check archive table
            from sqlalchemy import select as sa_select

            q = sa_select(ReportArchive).where(ReportArchive.id == report_id)
            archived = (await db.execute(q)).scalar_one_or_none()
            if archived is None:
                return None
            # Return as a transient Report-like object for response building
            return archived
        return instance

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

    @cached("intelflow", "list_topics", ttl=1800, key_params=("space_id",))
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
        # Generate embedding for topic name
        embedding = await get_embedding(data.name)
        if embedding:
            topic.embedding = embedding
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
        embedding = await get_embedding(name)
        if embedding:
            topic.embedding = embedding
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
        # Sync counts to be accurate
        await self.sync_report_counts(db, space_id)
        return {"reports_processed": len(reports), "topic_links_created": total_links}

    async def sync_report_counts(self, db: AsyncSession, space_id: str) -> int:
        """Rebuild report_count for all topics in a space."""
        topics = (await db.execute(select(Topic).where(Topic.space_id == space_id))).scalars().all()
        count = 0
        for topic in topics:
            cnt = (
                await db.execute(
                    select(func.count())
                    .select_from(ReportTopic)
                    .where(ReportTopic.topic_id == topic.id)
                )
            ).scalar_one()
            topic.report_count = cnt
            count += 1
        await db.flush()
        return count

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

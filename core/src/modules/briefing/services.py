"""Briefing services — CRUD for topics, analysts, briefings, entries, follow-ups.

This is the PUBLIC API of the briefing module.
"""

import asyncio
import logging
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.bus import Event, event_bus
from src.shared.embedding import get_embedding
from src.shared.errors import NotFoundError
from src.shared.fsm import emit_state_changed, validate_transition
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService

from .events import BriefingEvents
from .lifecycle import BriefingLifecycle, EntryPhase
from .models import (
    Briefing,
    BriefingAnalyst,
    BriefingEntry,
    BriefingFollowUp,
    BriefingSubtopic,
    BriefingTopic,
)
from .schemas import (
    AnalystCreate,
    AnalystResponse,
    AnalystUpdate,
    BriefingCreate,
    BriefingEntryCreate,
    BriefingEntryResponse,
    BriefingResponse,
    BriefingSubtopicCreate,
    BriefingSubtopicResponse,
    BriefingSubtopicUpdate,
    BriefingTopicCreate,
    BriefingTopicResponse,
    BriefingTopicUpdate,
    BriefingUpdate,
    DailySummaryResponse,
    DomainSummary,
    FollowUpCreate,
    FollowUpResponse,
)

logger = logging.getLogger(__name__)

# ======================== Topic Service ========================


class BriefingTopicService(
    BaseCRUDService[BriefingTopic, BriefingTopicCreate, BriefingTopicUpdate, BriefingTopicResponse]
):
    model = BriefingTopic
    audit_module = "briefing"
    audit_entity_type = "briefing_topics"

    def to_response(self, instance: BriefingTopic) -> BriefingTopicResponse:
        subtopics = []
        if hasattr(instance, "subtopics") and instance.subtopics:
            subtopics = [
                BriefingSubtopicResponse(
                    id=s.id,
                    space_id=s.space_id,
                    created_by=s.created_by,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                    topic_id=s.topic_id,
                    name=s.name,
                    parameters=s.parameters or {},
                    enabled=s.enabled,
                )
                for s in instance.subtopics
            ]
        return BriefingTopicResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            name=instance.name,
            display_name=instance.display_name,
            description=instance.description,
            enabled=instance.enabled,
            priority=instance.priority,
            prompt_template=instance.prompt_template,
            sources=instance.sources or [],
            schedule=instance.schedule,
            search_config=instance.search_config or {},
            topic_type=instance.topic_type or "news",
            subtopics=subtopics,
        )

    async def toggle(self, db: AsyncSession, topic_id: str) -> BriefingTopicResponse:
        instance = await db.get(BriefingTopic, topic_id)
        if not instance:
            raise NotFoundError("Briefing topic not found", code="briefing.topic_not_found")
        instance.enabled = not instance.enabled
        await db.flush()
        return self.to_response(instance)

    async def add_subtopic(
        self,
        db: AsyncSession,
        topic_id: str,
        space_id: str,
        data: BriefingSubtopicCreate,
        user_id: str | None = None,
    ) -> BriefingSubtopicResponse:
        parent = await db.get(BriefingTopic, topic_id)
        if not parent:
            raise NotFoundError("Briefing topic not found", code="briefing.topic_not_found")
        subtopic = BriefingSubtopic(
            topic_id=topic_id,
            space_id=space_id,
            created_by=user_id,
            name=data.name,
            parameters=data.parameters,
            enabled=data.enabled,
        )
        db.add(subtopic)
        await db.flush()
        return BriefingSubtopicResponse(
            id=subtopic.id,
            space_id=subtopic.space_id,
            created_by=subtopic.created_by,
            created_at=subtopic.created_at,
            updated_at=subtopic.updated_at,
            topic_id=subtopic.topic_id,
            name=subtopic.name,
            parameters=subtopic.parameters or {},
            enabled=subtopic.enabled,
        )

    async def update_subtopic(
        self, db: AsyncSession, subtopic_id: str, data: BriefingSubtopicUpdate
    ) -> BriefingSubtopicResponse:
        subtopic = await db.get(BriefingSubtopic, subtopic_id)
        if not subtopic:
            raise NotFoundError("Subtopic not found", code="briefing.subtopic_not_found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(subtopic, key, value)
        await db.flush()
        return BriefingSubtopicResponse(
            id=subtopic.id,
            space_id=subtopic.space_id,
            created_by=subtopic.created_by,
            created_at=subtopic.created_at,
            updated_at=subtopic.updated_at,
            topic_id=subtopic.topic_id,
            name=subtopic.name,
            parameters=subtopic.parameters or {},
            enabled=subtopic.enabled,
        )

    async def delete_subtopic(self, db: AsyncSession, subtopic_id: str) -> bool:
        subtopic = await db.get(BriefingSubtopic, subtopic_id)
        if not subtopic:
            return False
        await db.delete(subtopic)
        await db.flush()
        return True

    async def seed_defaults(
        self, db: AsyncSession, space_id: str, user_id: str | None = None
    ) -> list[BriefingTopicResponse]:
        """Seed default briefing topics if none exist."""
        count = (
            await db.execute(
                select(func.count())
                .select_from(BriefingTopic)
                .where(BriefingTopic.space_id == space_id)
            )
        ).scalar_one()
        if count > 0:
            return []

        defaults: list[dict[str, Any]] = [
            {
                "name": "finance",
                "display_name": "全球金融市場",
                "description": "全球金融市場動態、匯率、加密貨幣與投資趨勢",
                "schedule": "daily",
                "priority": 1,
                "topic_type": "news",
                "search_config": {
                    "search_query_en": "global finance stock market",
                    "focus_areas": (
                        "股市動態、央行政策、利率走勢、外匯變動、大宗商品、加密貨幣、IPO、併購"
                    ),
                    "subreddits": "wallstreetbets OR investing OR stocks OR cryptocurrency",
                },
            },
            {
                "name": "ai",
                "display_name": "AI國際局勢",
                "description": "各國AI政策監管、模型發布與技術突破",
                "schedule": "daily",
                "priority": 2,
                "topic_type": "news",
                "search_config": {
                    "search_query_en": "AI artificial intelligence regulation policy",
                    "focus_areas": (
                        "各國AI政策監管、模型發布、公司動態（OpenAI/Anthropic/Google/Meta/xAI）"  # noqa: RUF001
                        "、AI安全倫理、就業影響"
                    ),
                    "subreddits": "MachineLearning OR artificial OR LocalLLaMA",
                },
            },
            {
                "name": "tech",
                "display_name": "科技產業",
                "description": "大型科技公司動態、半導體、新創融資與開源生態",
                "schedule": "daily",
                "priority": 3,
                "topic_type": "news",
                "search_config": {
                    "search_query_en": "technology industry semiconductor",
                    "focus_areas": (
                        "大型科技公司動態、半導體（台積電/NVIDIA）、新創融資、雲端服務、開源生態"  # noqa: RUF001
                    ),
                    "subreddits": "technology OR programming OR startups",
                },
            },
            {
                "name": "geopolitics",
                "display_name": "地緣政治",
                "description": "台海局勢、中美競爭、俄烏戰爭與印太戰略",
                "schedule": "daily",
                "priority": 4,
                "topic_type": "news",
                "search_config": {
                    "search_query_en": "geopolitics international relations",
                    "focus_areas": "台海局勢、中美競爭、俄烏戰爭、中東局勢、印太戰略",
                    "subreddits": "geopolitics OR worldnews OR taiwan",
                },
            },
            {
                "name": "weather",
                "display_name": "天氣概覽",
                "description": "關注城市天氣預報與氣候變化",
                "schedule": "daily",
                "priority": 5,
                "topic_type": "weather",
                "search_config": {
                    "cities": [
                        {"name_en": "Tucheng", "name_cn": "土城"},
                        {"name_en": "Kaohsiung", "name_cn": "高雄"},
                        {"name_en": "Shanghai", "name_cn": "上海"},
                        {"name_en": "Taichung", "name_cn": "台中"},
                        {"name_en": "Yunlin", "name_cn": "雲林"},
                    ],
                    "content_priorities": ["一週天氣預報", "降雨機率", "空氣品質", "紫外線指數"],
                },
            },
            {
                "name": "devtools",
                "display_name": "開發工具政策",
                "description": "Claude Code/Gemini CLI/Codex CLI 政策與第三方工具相容性",
                "schedule": "daily",
                "priority": 6,
                "topic_type": "news",
                "search_config": {
                    "search_query_en": "Claude Code Gemini CLI Codex CLI policy",
                    "focus_areas": (
                        "Claude Code/Anthropic ToS、Gemini CLI/Google API政策"
                        "、Codex CLI/OpenAI政策、第三方工具相容性、MCP伺服器政策"
                    ),
                    "subreddits": "ClaudeAI OR ChatGPT OR LocalLLaMA",
                },
            },
        ]

        results: list[BriefingTopicResponse] = []
        for topic_data in defaults:
            subtopics_data = topic_data.pop("subtopics", [])
            create_data = BriefingTopicCreate(**topic_data)
            instance = BriefingTopic(
                space_id=space_id,
                created_by=user_id,
                **create_data.model_dump(),
            )
            db.add(instance)
            await db.flush()

            for sub in subtopics_data:
                sub_obj = BriefingSubtopic(
                    topic_id=instance.id,
                    space_id=space_id,
                    created_by=user_id,
                    name=sub["name"],
                    parameters=sub.get("parameters", {}),
                    enabled=True,
                )
                db.add(sub_obj)
            await db.flush()
            await db.refresh(instance, ["subtopics"])
            results.append(self.to_response(instance))

        return results


# ======================== Analyst Service ========================


class AnalystService(
    BaseCRUDService[BriefingAnalyst, AnalystCreate, AnalystUpdate, AnalystResponse]
):
    model = BriefingAnalyst
    audit_module = "briefing"
    audit_entity_type = "briefing_analysts"

    def to_response(self, instance: BriefingAnalyst) -> AnalystResponse:
        return AnalystResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            name=instance.name,
            display_name=instance.display_name,
            color=instance.color,
            avatar_url=instance.avatar_url,
            model_id=instance.model_id,
            system_prompt=instance.system_prompt,
            cli_command=instance.cli_command,
            enabled=instance.enabled,
            priority=instance.priority,
        )

    async def toggle(self, db: AsyncSession, analyst_id: str) -> AnalystResponse:
        instance = await db.get(BriefingAnalyst, analyst_id)
        if not instance:
            raise NotFoundError("Analyst not found", code="briefing.analyst_not_found")
        instance.enabled = not instance.enabled
        await db.flush()
        return self.to_response(instance)

    async def seed_defaults(
        self, db: AsyncSession, space_id: str, user_id: str | None = None
    ) -> list[AnalystResponse]:
        """Seed default analysts if none exist."""
        count = (
            await db.execute(
                select(func.count())
                .select_from(BriefingAnalyst)
                .where(BriefingAnalyst.space_id == space_id)
            )
        ).scalar_one()
        if count > 0:
            return []

        defaults = [
            {
                "name": "claude",
                "display_name": "Claude",
                "color": "#c4a7e7",
                "model_id": "claude-sonnet-4-6",
                "system_prompt": "你是一位嚴謹的資深分析師，擅長深度分析與邏輯推理。",  # noqa: RUF001
                "cli_command": "claude",
                "priority": 1,
            },
            {
                "name": "codex",
                "display_name": "Codex",
                "color": "#9ccfd8",
                "model_id": "o3",
                "system_prompt": "你是一位注重數據和技術細節的分析師，擅長量化分析。",  # noqa: RUF001
                "cli_command": "codex",
                "priority": 2,
            },
            {
                "name": "gemini",
                "display_name": "Gemini",
                "color": "#f6c177",
                "model_id": "gemini-2.5-flash",
                "system_prompt": "你是一位善於提出不同觀點的分析師，擅長逆向思考。",  # noqa: RUF001
                "cli_command": "gemini",
                "priority": 3,
            },
        ]

        results: list[AnalystResponse] = []
        for data in defaults:
            instance = BriefingAnalyst(space_id=space_id, created_by=user_id, **data)
            db.add(instance)
            await db.flush()
            results.append(self.to_response(instance))
        return results


# ======================== Briefing Service ========================


class BriefingService:
    """Daily briefing operations."""

    async def list_briefings(
        self,
        db: AsyncSession,
        space_id: str,
        date_from: date | None = None,
        date_to: date | None = None,
        topic_id: str | None = None,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[BriefingResponse]:
        p = pagination or PaginationParams()
        base = select(Briefing).where(Briefing.space_id == space_id)
        if date_from:
            base = base.where(Briefing.date >= date_from)
        if date_to:
            base = base.where(Briefing.date <= date_to)
        if topic_id:
            base = base.where(Briefing.topic_id == topic_id)

        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = (
            base.order_by(Briefing.date.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[BriefingResponse](
            items=[self._to_response(b) for b in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def get_by_date(
        self, db: AsyncSession, space_id: str, target_date: date
    ) -> list[BriefingResponse]:
        q = (
            select(Briefing)
            .where(Briefing.space_id == space_id, Briefing.date == target_date)
            .order_by(Briefing.domain)
        )
        rows = (await db.execute(q)).scalars().all()
        return [self._to_response(b) for b in rows]

    async def get_by_date_and_topic(
        self, db: AsyncSession, space_id: str, target_date: date, domain: str
    ) -> BriefingResponse | None:
        q = select(Briefing).where(
            Briefing.space_id == space_id,
            Briefing.date == target_date,
            Briefing.domain == domain,
        )
        instance = (await db.execute(q)).scalar_one_or_none()
        if not instance:
            return None
        return self._to_response(instance)

    async def get_daily_summary(
        self, db: AsyncSession, space_id: str, target_date: date
    ) -> DailySummaryResponse:
        """Merged conclusion view for a given date."""
        briefings = await self.get_by_date(db, space_id, target_date)
        if not briefings:
            return DailySummaryResponse(date=target_date, status="empty")

        domains: list[DomainSummary] = []
        all_consensus: list[str] = []
        all_dissent: list[dict] = []
        all_confidences: list[float] = []
        conclusions: list[str] = []
        total_follow_ups = 0
        worst_status = "completed"

        for b in briefings:
            raw_count = sum(1 for e in b.entries if e.phase == "raw")
            analysis_count = sum(1 for e in b.entries if e.phase == "analysis")
            conclusion_entry = next((e for e in b.entries if e.phase == "conclusion"), None)

            domains.append(
                DomainSummary(
                    domain=b.domain,
                    display_name=b.domain,
                    briefing_id=b.id,
                    status=b.status,
                    sources_count=raw_count,
                    analysts_count=analysis_count,
                    has_conclusion=conclusion_entry is not None,
                )
            )

            if conclusion_entry:
                conclusions.append(conclusion_entry.content)
                meta = conclusion_entry.metadata or {}
                all_consensus.extend(meta.get("consensus_points", []))
                all_dissent.extend(meta.get("dissent_points", []))
                if "confidence" in meta:
                    all_confidences.append(meta["confidence"])

            total_follow_ups += len(b.follow_ups)

            if b.status in ("failed",):
                worst_status = "failed"
            elif b.status != "completed" and worst_status != "failed":
                worst_status = b.status

        avg_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else None

        return DailySummaryResponse(
            date=target_date,
            status=worst_status,
            domains=domains,
            merged_conclusion="\n\n---\n\n".join(conclusions) if conclusions else None,
            consensus_points=all_consensus,
            dissent_points=all_dissent,
            confidence=avg_confidence,
            briefing_ids=[b.id for b in briefings],
            follow_up_count=total_follow_ups,
        )

    async def create_briefing(
        self,
        db: AsyncSession,
        space_id: str,
        data: BriefingCreate,
        user_id: str | None = None,
    ) -> BriefingResponse:
        briefing = Briefing(
            space_id=space_id,
            created_by=user_id,
            date=data.date,
            topic_id=data.topic_id,
            domain=data.domain,
            status=data.status,
            raw_data=data.raw_data,
            analyses=data.analyses,
            debate=data.debate,
        )
        if data.debate:
            try:
                embedding = await get_embedding(data.debate)
                if embedding:
                    briefing.embedding = embedding
            except Exception:
                logger.warning(
                    "get_embedding failed for briefing debate, continuing without embedding",
                    exc_info=True,
                )
        db.add(briefing)
        await db.flush()
        await db.refresh(briefing, ["entries", "follow_ups"])
        try:
            await event_bus.publish(
                Event(
                    type=BriefingEvents.DAILY_COMPLETED,
                    data={
                        "briefing_id": briefing.id,
                        "date": str(data.date),
                        "domain": data.domain,
                    },
                    source="briefing",
                    user_id=user_id,
                )
            )
        except Exception:
            logger.warning("Failed to publish DAILY_COMPLETED event", exc_info=True)
        return self._to_response(briefing)

    async def update_status(
        self, db: AsyncSession, briefing_id: str, data: BriefingUpdate
    ) -> BriefingResponse:
        q = select(Briefing).where(Briefing.id == briefing_id)
        instance = (await db.execute(q)).scalar_one_or_none()
        if not instance:
            raise NotFoundError("Briefing not found", code="briefing.not_found")
        old_status = instance.status
        if data.status:
            validate_transition(
                BriefingLifecycle, instance.status, data.status, entity_type="briefing"
            )
            instance.status = data.status
        await db.flush()
        await db.refresh(instance)

        if data.status and old_status != data.status:
            await emit_state_changed("briefing", "briefing", instance.id, old_status, data.status)

        return self._to_response(instance)

    # Phase ordering for determining the latest phase in a briefing's entries
    _PHASE_ORDER = {p: i for i, p in enumerate(("raw", "analysis", "debate", "conclusion"))}

    async def add_entry(
        self,
        db: AsyncSession,
        briefing_id: str,
        space_id: str,
        data: BriefingEntryCreate,
        user_id: str | None = None,
    ) -> BriefingEntryResponse:
        # Validate entry phase: allow same phase (multiple entries per phase),
        # allow forward transitions, prohibit phase regression.
        existing_q = select(BriefingEntry.phase).where(BriefingEntry.briefing_id == briefing_id)
        existing_phases = (await db.execute(existing_q)).scalars().all()
        if existing_phases:
            latest_phase = max(existing_phases, key=lambda p: self._PHASE_ORDER.get(p, -1))
            # Same phase is always OK (multiple entries per phase)
            if data.phase != latest_phase:
                validate_transition(
                    EntryPhase, latest_phase, data.phase, entity_type="briefing_entry"
                )
        else:
            # No entries yet — only the initial phase (raw) is valid
            if data.phase != "raw":
                validate_transition(EntryPhase, "raw", data.phase, entity_type="briefing_entry")
        entry = BriefingEntry(
            briefing_id=briefing_id,
            space_id=space_id,
            created_by=user_id,
            phase=data.phase,
            key=data.key,
            content=data.content,
            meta=data.metadata,
        )
        try:
            embedding = await get_embedding(data.content)
            if embedding:
                entry.embedding = embedding
        except Exception:
            logger.warning(
                "get_embedding failed for briefing entry, continuing without embedding",
                exc_info=True,
            )
        db.add(entry)
        await db.flush()
        return self._entry_to_response(entry)

    async def get_entries(
        self, db: AsyncSession, briefing_id: str, phase: str | None = None
    ) -> list[BriefingEntryResponse]:
        q = select(BriefingEntry).where(BriefingEntry.briefing_id == briefing_id)
        if phase:
            q = q.where(BriefingEntry.phase == phase)
        q = q.order_by(BriefingEntry.phase, BriefingEntry.key)
        rows = (await db.execute(q)).scalars().all()
        return [self._entry_to_response(e) for e in rows]

    def _to_response(self, instance: Briefing) -> BriefingResponse:
        entries = []
        conclusion = None
        conclusion_meta = None
        follow_ups: list[FollowUpResponse] = []

        if instance.entries:
            entries = [self._entry_to_response(e) for e in instance.entries]
            for e in instance.entries:
                if e.phase == "conclusion":
                    conclusion = e.content
                    conclusion_meta = e.meta

        if instance.follow_ups:
            follow_ups = [self._follow_up_to_response(f) for f in instance.follow_ups]

        return BriefingResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            date=instance.date,
            topic_id=instance.topic_id,
            domain=instance.domain,
            status=instance.status,
            raw_data=instance.raw_data,
            analyses=instance.analyses,
            debate=instance.debate,
            entries=entries,
            conclusion=conclusion,
            conclusion_meta=conclusion_meta,
            follow_ups=follow_ups,
        )

    def _entry_to_response(self, entry: BriefingEntry) -> BriefingEntryResponse:
        return BriefingEntryResponse(
            id=entry.id,
            space_id=entry.space_id,
            created_by=entry.created_by,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            briefing_id=entry.briefing_id,
            phase=entry.phase,
            key=entry.key,
            content=entry.content,
            metadata=entry.meta or {},
        )

    def _follow_up_to_response(self, fu: BriefingFollowUp) -> FollowUpResponse:
        return FollowUpResponse(
            id=fu.id,
            space_id=fu.space_id,
            created_by=fu.created_by,
            created_at=fu.created_at,
            updated_at=fu.updated_at,
            briefing_id=fu.briefing_id,
            question=fu.question,
            answer=fu.answer,
            status=fu.status,
            metadata=fu.meta or {},
        )


# ======================== Follow-Up Service ========================


class FollowUpService:
    """Manage follow-up questions on briefings."""

    async def list_follow_ups(self, db: AsyncSession, briefing_id: str) -> list[FollowUpResponse]:
        q = (
            select(BriefingFollowUp)
            .where(BriefingFollowUp.briefing_id == briefing_id)
            .order_by(BriefingFollowUp.created_at)
        )
        rows = (await db.execute(q)).scalars().all()
        return [self._to_response(f) for f in rows]

    async def create_follow_up(
        self,
        db: AsyncSession,
        briefing_id: str,
        space_id: str,
        data: FollowUpCreate,
        user_id: str | None = None,
    ) -> FollowUpResponse:
        # Verify briefing exists
        briefing = await db.get(Briefing, briefing_id)
        if not briefing:
            raise NotFoundError("Briefing not found", code="briefing.not_found")

        fu = BriefingFollowUp(
            briefing_id=briefing_id,
            space_id=space_id,
            created_by=user_id,
            question=data.question,
            status="pending",
        )
        db.add(fu)
        await db.flush()

        try:
            await event_bus.publish(
                Event(
                    type=BriefingEvents.FOLLOW_UP_ASKED,
                    data={
                        "follow_up_id": fu.id,
                        "briefing_id": briefing_id,
                        "question": data.question,
                    },
                    source="briefing",
                    user_id=user_id,
                )
            )
        except Exception:
            logger.warning("Failed to publish FOLLOW_UP_ASKED event", exc_info=True)
        return self._to_response(fu)

    async def answer_follow_up(
        self,
        db: AsyncSession,
        follow_up_id: str,
        space_id: str,
    ) -> FollowUpResponse:
        """Generate an LLM answer for a follow-up question."""
        fu = await db.get(BriefingFollowUp, follow_up_id)
        if not fu:
            raise NotFoundError("Follow-up not found", code="briefing.follow_up_not_found")

        # Gather context from the briefing's entries
        entries_q = (
            select(BriefingEntry)
            .where(BriefingEntry.briefing_id == fu.briefing_id)
            .order_by(BriefingEntry.phase, BriefingEntry.key)
        )
        entries = (await db.execute(entries_q)).scalars().all()
        context_parts = []
        for e in entries:
            context_parts.append(f"[{e.phase}/{e.key}]\n{e.content}")
        context = "\n\n---\n\n".join(context_parts)

        prompt = (
            f"以下是一份每日簡報的完整資料：\n\n{context}\n\n"  # noqa: RUF001
            f"使用者提問：{fu.question}\n\n"  # noqa: RUF001
            "請用繁體中文回答，簡潔扼要，引用上方資料中的具體內容。"  # noqa: RUF001
        )

        fu.status = "answering"
        await db.flush()

        try:
            answer = await asyncio.to_thread(
                self._run_claude_answer, prompt
            )
            fu.answer = answer
            fu.status = "answered"
        except Exception:
            logger.warning("Failed to generate follow-up answer", exc_info=True)
            fu.status = "failed"

        await db.flush()
        return self._to_response(fu)

    @staticmethod
    def _run_claude_answer(prompt: str) -> str:
        """Run Claude CLI to generate follow-up answer (blocking)."""
        import os
        import re

        env = os.environ.copy()
        home = str(Path.home())
        env["PATH"] = f"{home}/.local/bin:/opt/homebrew/bin:/usr/local/bin:{env.get('PATH', '')}"
        env.pop("CLAUDECODE", None)

        result = subprocess.run(  # noqa: S603
            ["claude", "-p", prompt, "--model", "haiku"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        ansi_re = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]|\r")
        return ansi_re.sub("", result.stdout).strip()

    def _to_response(self, fu: BriefingFollowUp) -> FollowUpResponse:
        return FollowUpResponse(
            id=fu.id,
            space_id=fu.space_id,
            created_by=fu.created_by,
            created_at=fu.created_at,
            updated_at=fu.updated_at,
            briefing_id=fu.briefing_id,
            question=fu.question,
            answer=fu.answer,
            status=fu.status,
            metadata=fu.meta or {},
        )


# ======================== Module-level singletons ========================

briefing_topic_service = BriefingTopicService()
analyst_service = AnalystService()
briefing_service = BriefingService()
follow_up_service = FollowUpService()

"""Paper services — CRUD + dashboard (standalone, no EventBus/cache deps).

Adapted from core/src/modules/paper/services.py.
Removed: PaperEvents, @cached decorator, audit trail.
"""

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from svc_shared.schemas import PaginatedResponse, PaginationParams
from svc_shared.services import BaseCRUDService

from .models import Annotation, Article, Digest
from .schemas import (
    AnnotationCreate,
    AnnotationResponse,
    AnnotationUpdate,
    ArticleBrief,
    ArticleCreate,
    ArticleResponse,
    ArticleUpdate,
    DashboardResponse,
    DigestCreate,
    DigestResponse,
    DigestUpdate,
)

logger = logging.getLogger(__name__)


def _digest_to_response(instance: Digest) -> DigestResponse:
    return DigestResponse(
        id=instance.id,
        space_id=instance.space_id,
        created_by=instance.created_by,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
        paper_id=instance.paper_id,
        one_liner=instance.one_liner,
        key_findings=instance.key_findings or [],
        workshop_relevance=instance.workshop_relevance,
        applicable_modules=instance.applicable_modules or [],
        actionable_insight=instance.actionable_insight,
        effort_estimate=instance.effort_estimate,
        confidence=instance.confidence,
        model_used=instance.model_used,
        generated_at=instance.generated_at,
    )


class ArticleService(BaseCRUDService[Article, ArticleCreate, ArticleUpdate, ArticleResponse]):
    model = Article

    def before_create(self, data: ArticleCreate, **kwargs: Any) -> dict:
        return data.model_dump()

    def to_response(self, instance: Article) -> ArticleResponse:
        digest_resp = None
        if hasattr(instance, "digest") and instance.digest:
            digest_resp = _digest_to_response(instance.digest)
        return ArticleResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            title=instance.title,
            abstract=instance.abstract,
            arxiv_id=instance.arxiv_id,
            doi=instance.doi,
            year=instance.year,
            authors=instance.authors or [],
            journal=instance.journal,
            categories=instance.categories or [],
            tags=instance.tags or [],
            pdf_url=instance.pdf_url,
            source_url=instance.source_url,
            full_text=instance.full_text,
            s3_uri=instance.s3_uri,
            digest=digest_resp,
        )

    def to_brief(self, instance: Article) -> ArticleBrief:
        return ArticleBrief(
            id=instance.id,
            title=instance.title,
            arxiv_id=instance.arxiv_id,
            doi=instance.doi,
            year=instance.year,
            authors=instance.authors or [],
            categories=instance.categories or [],
            tags=instance.tags or [],
            created_at=instance.created_at,
        )

    async def get_by_arxiv_id(self, db: AsyncSession, arxiv_id: str) -> Article | None:
        q = select(Article).where(Article.arxiv_id == arxiv_id, Article.deleted_at == None)  # noqa: E711
        return (await db.execute(q)).scalar_one_or_none()

    async def get_by_doi(self, db: AsyncSession, doi: str) -> Article | None:
        q = select(Article).where(Article.doi == doi, Article.deleted_at == None)  # noqa: E711
        return (await db.execute(q)).scalar_one_or_none()

    async def list_by_tags(
        self,
        db: AsyncSession,
        space_id: str,
        tags: list[str],
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[ArticleResponse]:
        p = pagination or PaginationParams()
        base = select(Article).where(
            Article.space_id == space_id,
            Article.tags.contains(tags),
            Article.deleted_at == None,  # noqa: E711
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = (
            base.order_by(Article.created_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[ArticleResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


class DigestService(BaseCRUDService[Digest, DigestCreate, DigestUpdate, DigestResponse]):
    model = Digest

    def before_create(self, data: DigestCreate, **kwargs: Any) -> dict:
        return data.model_dump()

    def to_response(self, instance: Digest) -> DigestResponse:
        return _digest_to_response(instance)

    async def get_by_paper_id(self, db: AsyncSession, paper_id: str) -> Digest | None:
        q = select(Digest).where(Digest.paper_id == paper_id, Digest.deleted_at == None)  # noqa: E711
        return (await db.execute(q)).scalar_one_or_none()

    async def upsert(
        self,
        db: AsyncSession,
        space_id: str,
        paper_id: str,
        data: DigestCreate,
        user_id: str | None = None,
    ) -> Digest:
        existing = await self.get_by_paper_id(db, paper_id)
        if existing:
            update_data = DigestUpdate(**data.model_dump(exclude={"paper_id"}))
            return await self.update(db, existing.id, update_data, user_id=user_id)
        return await self.create(db, space_id, data, user_id=user_id)


class AnnotationService(
    BaseCRUDService[Annotation, AnnotationCreate, AnnotationUpdate, AnnotationResponse]
):
    model = Annotation

    def before_create(self, data: AnnotationCreate, **kwargs: Any) -> dict:
        d = data.model_dump()
        paper_id = kwargs.get("paper_id")
        if paper_id:
            d["paper_id"] = paper_id
        return d

    def to_response(self, instance: Annotation) -> AnnotationResponse:
        return AnnotationResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            paper_id=instance.paper_id,
            note=instance.note,
            annotation_type=instance.annotation_type,
            tags=instance.tags or [],
        )

    async def create_for_paper(
        self,
        db: AsyncSession,
        space_id: str,
        paper_id: str,
        data: AnnotationCreate,
        user_id: str | None = None,
    ) -> Annotation:
        kwargs = data.model_dump()
        kwargs["space_id"] = space_id
        kwargs["paper_id"] = paper_id
        if user_id:
            kwargs["created_by"] = user_id
        instance = Annotation(**kwargs)
        db.add(instance)
        await db.flush()
        return instance

    async def list_by_paper(
        self,
        db: AsyncSession,
        paper_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[AnnotationResponse]:
        p = pagination or PaginationParams()
        base = select(Annotation).where(
            Annotation.paper_id == paper_id,
            Annotation.deleted_at == None,  # noqa: E711
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = (
            base.order_by(Annotation.created_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[AnnotationResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


class DashboardService:
    async def get_summary(self, db: AsyncSession, space_id: str) -> DashboardResponse:
        stats_q = select(
            select(func.count())
            .select_from(Article)
            .where(Article.space_id == space_id, Article.deleted_at == None)
            .correlate(None)  # noqa: E711
            .scalar_subquery()
            .label("total_articles"),
            select(func.count())
            .select_from(Digest)
            .where(Digest.space_id == space_id, Digest.deleted_at == None)
            .correlate(None)  # noqa: E711
            .scalar_subquery()
            .label("total_digests"),
            select(func.count())
            .select_from(Annotation)
            .where(Annotation.space_id == space_id, Annotation.deleted_at == None)
            .correlate(None)  # noqa: E711
            .scalar_subquery()
            .label("total_annotations"),
            select(func.count())
            .select_from(Digest)
            .where(
                Digest.space_id == space_id,
                Digest.workshop_relevance == "high",
                Digest.deleted_at == None,
            )  # noqa: E711
            .correlate(None)
            .scalar_subquery()
            .label("high_relevance_count"),
        )
        stats = (await db.execute(stats_q)).one()
        recent_rows = (
            (
                await db.execute(
                    select(Article)
                    .where(Article.space_id == space_id, Article.deleted_at == None)  # noqa: E711
                    .order_by(Article.created_at.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        return DashboardResponse(
            total_articles=stats.total_articles,
            total_digests=stats.total_digests,
            total_annotations=stats.total_annotations,
            high_relevance_count=stats.high_relevance_count,
            recent_articles=[
                ArticleBrief(
                    id=a.id,
                    title=a.title,
                    arxiv_id=a.arxiv_id,
                    doi=a.doi,
                    year=a.year,
                    authors=a.authors or [],
                    categories=a.categories or [],
                    tags=a.tags or [],
                    created_at=a.created_at,
                )
                for a in recent_rows
            ],
        )


article_service = ArticleService()
digest_service = DigestService()
annotation_service = AnnotationService()
dashboard_service = DashboardService()

"""Paper services — CRUD + digest + annotation + dashboard.

This is the PUBLIC API of the paper module.
Other modules import from here, never from models.py.
"""

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.types import PaperEvents
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService

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

# ======================== Article Service ========================


class ArticleService(BaseCRUDService[Article, ArticleCreate, ArticleUpdate, ArticleResponse]):
    model = Article
    audit_module = "paper"
    audit_entity_type = "articles"
    event_types = {
        "created": PaperEvents.ARTICLE_CREATED,
        "updated": PaperEvents.ARTICLE_UPDATED,
        "deleted": PaperEvents.ARTICLE_DELETED,
    }
    event_id_alias = "article_id"
    event_fields = ("title", "abstract", "arxiv_id", "doi", "year", "categories", "tags")

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
            journal=instance.journal,
            categories=instance.categories or [],
            tags=instance.tags or [],
            created_at=instance.created_at,
        )

    async def get_by_arxiv_id(self, db: AsyncSession, arxiv_id: str) -> Article | None:
        """Dedup check by arXiv ID."""
        q = select(Article).where(
            Article.arxiv_id == arxiv_id,
            Article.deleted_at == None,  # noqa: E711
        )
        return (await db.execute(q)).scalar_one_or_none()

    async def get_by_doi(self, db: AsyncSession, doi: str) -> Article | None:
        """Dedup check by DOI."""
        q = select(Article).where(
            Article.doi == doi,
            Article.deleted_at == None,  # noqa: E711
        )
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


# ======================== Digest Service ========================


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


class DigestService(BaseCRUDService[Digest, DigestCreate, DigestUpdate, DigestResponse]):
    model = Digest
    audit_module = "paper"
    audit_entity_type = "digests"
    event_types = {"created": PaperEvents.DIGEST_GENERATED}
    event_fields = (
        "paper_id", "workshop_relevance", "applicable_modules", "model_used", "confidence",
    )

    def before_create(self, data: DigestCreate, **kwargs: Any) -> dict:
        return data.model_dump()

    def to_response(self, instance: Digest) -> DigestResponse:
        return _digest_to_response(instance)

    async def get_by_paper_id(self, db: AsyncSession, paper_id: str) -> Digest | None:
        """Get digest for a specific article."""
        q = select(Digest).where(
            Digest.paper_id == paper_id,
            Digest.deleted_at == None,  # noqa: E711
        )
        return (await db.execute(q)).scalar_one_or_none()

    async def upsert(
        self,
        db: AsyncSession,
        space_id: str,
        paper_id: str,
        data: DigestCreate,
        user_id: str | None = None,
    ) -> Digest:
        """Create or replace digest for a paper (1:1 relationship)."""
        existing = await self.get_by_paper_id(db, paper_id)
        if existing:
            # Update existing digest
            update_data = DigestUpdate(**data.model_dump(exclude={"paper_id"}))
            updated = await self.update(db, existing.id, update_data, user_id=user_id)
            return updated
        # Create new
        return await self.create(db, space_id, data, user_id=user_id)


# ======================== Annotation Service ========================


class AnnotationService(
    BaseCRUDService[Annotation, AnnotationCreate, AnnotationUpdate, AnnotationResponse]
):
    model = Annotation
    audit_module = "paper"
    audit_entity_type = "annotations"
    event_types = {"created": PaperEvents.ANNOTATION_CREATED}
    event_fields = ("paper_id", "annotation_type")

    def before_create(self, data: AnnotationCreate, **kwargs: Any) -> dict:
        d = data.model_dump()
        # paper_id must be injected from caller via kwargs
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

    async def create_for_paper(
        self,
        db: AsyncSession,
        space_id: str,
        paper_id: str,
        data: AnnotationCreate,
        user_id: str | None = None,
    ) -> Annotation:
        """Create annotation with paper_id injected."""
        kwargs = data.model_dump()
        kwargs["space_id"] = space_id
        kwargs["paper_id"] = paper_id
        if user_id:
            kwargs["created_by"] = user_id
        instance = Annotation(**kwargs)
        db.add(instance)
        await db.flush()
        self.after_create(instance)
        return instance


# ======================== Dashboard Service ========================


class DashboardService:
    """Statistics and summary data for the paper module."""

    async def get_summary(self, db: AsyncSession, space_id: str) -> DashboardResponse:
        total_articles = (
            await db.execute(
                select(func.count())
                .select_from(Article)
                .where(
                    Article.space_id == space_id,
                    Article.deleted_at == None,  # noqa: E711
                )
            )
        ).scalar_one()

        total_digests = (
            await db.execute(
                select(func.count())
                .select_from(Digest)
                .where(
                    Digest.space_id == space_id,
                    Digest.deleted_at == None,  # noqa: E711
                )
            )
        ).scalar_one()

        total_annotations = (
            await db.execute(
                select(func.count())
                .select_from(Annotation)
                .where(
                    Annotation.space_id == space_id,
                    Annotation.deleted_at == None,  # noqa: E711
                )
            )
        ).scalar_one()

        high_relevance_count = (
            await db.execute(
                select(func.count())
                .select_from(Digest)
                .where(
                    Digest.space_id == space_id,
                    Digest.workshop_relevance == "high",
                    Digest.deleted_at == None,  # noqa: E711
                )
            )
        ).scalar_one()

        # Recent articles
        recent_rows = (
            (
                await db.execute(
                    select(Article)
                    .where(
                        Article.space_id == space_id,
                        Article.deleted_at == None,  # noqa: E711
                    )
                    .order_by(Article.created_at.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        recent_articles = [
            ArticleBrief(
                id=a.id,
                title=a.title,
                arxiv_id=a.arxiv_id,
                doi=a.doi,
                year=a.year,
                authors=a.authors or [],
                journal=a.journal,
                categories=a.categories or [],
                tags=a.tags or [],
                created_at=a.created_at,
            )
            for a in recent_rows
        ]

        # Cannibalize candidates: high relevance + effort <= "3d"
        candidate_rows = (
            (
                await db.execute(
                    select(Article)
                    .join(Digest, Digest.paper_id == Article.id)
                    .where(
                        Article.space_id == space_id,
                        Article.deleted_at == None,  # noqa: E711
                        Digest.workshop_relevance == "high",
                        Digest.deleted_at == None,  # noqa: E711
                        Article.tags.contains(["cannibalize-candidate"]),
                    )
                    .order_by(Article.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        cannibalize_candidates = [
            ArticleBrief(
                id=a.id,
                title=a.title,
                arxiv_id=a.arxiv_id,
                doi=a.doi,
                year=a.year,
                authors=a.authors or [],
                journal=a.journal,
                categories=a.categories or [],
                tags=a.tags or [],
                created_at=a.created_at,
            )
            for a in candidate_rows
        ]

        return DashboardResponse(
            total_articles=total_articles,
            total_digests=total_digests,
            total_annotations=total_annotations,
            high_relevance_count=high_relevance_count,
            recent_articles=recent_articles,
            cannibalize_candidates=cannibalize_candidates,
        )


# ======================== Module-level singletons ========================

article_service = ArticleService()
digest_service = DigestService()
annotation_service = AnnotationService()
dashboard_service = DashboardService()

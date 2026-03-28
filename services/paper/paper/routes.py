"""Paper routes — REST API endpoints for standalone paper service.

Simplified from core/src/modules/paper/routes.py:
- No auth middleware (standalone service, auth handled at gateway)
- No embedding generation (Qdrant not available in standalone)
- No semantic search (requires Qdrant)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from svc_shared.database import get_db
from svc_shared.errors import ConflictError, NotFoundError
from svc_shared.schemas import PaginatedResponse, PaginationParams

from .schemas import (
    AnnotationCreate,
    AnnotationResponse,
    ArticleCreate,
    ArticleResponse,
    ArticleUpdate,
    DashboardResponse,
    DigestResponse,
)
from .services import (
    annotation_service,
    article_service,
    dashboard_service,
    digest_service,
)

router = APIRouter(tags=["paper"])


# ======================== Articles ========================


@router.get("/articles", response_model=PaginatedResponse[ArticleResponse])
async def list_articles(
    space_id: str = Query("default"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tag: str | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated tags"),
    db: AsyncSession = Depends(get_db),
):
    pagination = PaginationParams(page=page, page_size=page_size)
    tag_list = None
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    elif tag:
        tag_list = [tag]
    if tag_list:
        return await article_service.list_by_tags(db, space_id, tag_list, pagination)
    return await article_service.list(db, space_id, pagination)


@router.get("/articles/{article_id}", response_model=ArticleResponse)
async def get_article(article_id: str, db: AsyncSession = Depends(get_db)):
    instance = await article_service.get(db, article_id)
    if not instance:
        raise NotFoundError("Article not found", code="paper.article_not_found")
    return article_service.to_response(instance)


@router.post("/articles", response_model=ArticleResponse, status_code=201)
async def create_article(
    body: ArticleCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    if body.arxiv_id:
        existing = await article_service.get_by_arxiv_id(db, body.arxiv_id)
        if existing:
            raise ConflictError(
                f"Article with arxiv_id={body.arxiv_id} already exists",
                code="paper.arxiv_id_conflict",
            )
    if body.doi:
        existing = await article_service.get_by_doi(db, body.doi)
        if existing:
            raise ConflictError(
                f"Article with doi={body.doi} already exists", code="paper.doi_conflict"
            )
    instance = await article_service.create(db, space_id, body)
    await db.commit()
    await db.refresh(instance)
    return article_service.to_response(instance)


@router.put("/articles/{article_id}", response_model=ArticleResponse)
async def update_article(article_id: str, body: ArticleUpdate, db: AsyncSession = Depends(get_db)):
    instance = await article_service.update(db, article_id, body)
    if not instance:
        raise NotFoundError("Article not found", code="paper.article_not_found")
    await db.commit()
    await db.refresh(instance)
    return article_service.to_response(instance)


@router.delete("/articles/{article_id}", status_code=204)
async def delete_article(article_id: str, db: AsyncSession = Depends(get_db)):
    deleted = await article_service.delete(db, article_id)
    if not deleted:
        raise NotFoundError("Article not found", code="paper.article_not_found")
    await db.commit()


# ======================== Digest ========================


@router.get("/articles/{article_id}/digest", response_model=DigestResponse)
async def get_digest(article_id: str, db: AsyncSession = Depends(get_db)):
    article = await article_service.get(db, article_id)
    if not article:
        raise NotFoundError("Article not found", code="paper.article_not_found")
    digest = await digest_service.get_by_paper_id(db, article_id)
    if not digest:
        raise NotFoundError("Digest not found", code="paper.digest_not_found")
    return digest_service.to_response(digest)


# ======================== Annotations ========================


@router.get(
    "/articles/{article_id}/annotations", response_model=PaginatedResponse[AnnotationResponse]
)
async def list_annotations(
    article_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    article = await article_service.get(db, article_id)
    if not article:
        raise NotFoundError("Article not found", code="paper.article_not_found")
    pagination = PaginationParams(page=page, page_size=page_size)
    return await annotation_service.list_by_paper(db, article_id, pagination)


@router.post(
    "/articles/{article_id}/annotations", response_model=AnnotationResponse, status_code=201
)
async def create_annotation(
    article_id: str,
    body: AnnotationCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    article = await article_service.get(db, article_id)
    if not article:
        raise NotFoundError("Article not found", code="paper.article_not_found")
    instance = await annotation_service.create_for_paper(db, space_id, article_id, body)
    await db.commit()
    await db.refresh(instance)
    return annotation_service.to_response(instance)


# ======================== Dashboard ========================


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(space_id: str = Query("default"), db: AsyncSession = Depends(get_db)):
    return await dashboard_service.get_summary(db, space_id)


# ======================== Status ========================


@router.get("/status")
async def paper_status():
    return {"module": "paper", "status": "active", "service": "paper"}

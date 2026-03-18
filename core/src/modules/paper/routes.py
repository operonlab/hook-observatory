"""Paper routes — REST API endpoints.

Prefix: /api/paper (mounted in main.py)

Endpoints:
  GET/POST  /articles                        — list/create
  GET/PUT/DELETE /articles/{id}              — detail/update/delete
  POST      /search                          — semantic search
  GET       /articles/{id}/digest            — get digest
  POST      /articles/{id}/digest/trigger    — trigger digest generation
  GET/POST  /articles/{id}/annotations       — list/create annotations
  GET       /dashboard                       — stats
  GET       /status                          — health check
  POST      /digest/redigest                 — batch re-generate digests
  POST      /fetch/arxiv                     — import single paper from arXiv
"""

import asyncio
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.deps import get_db, require_permission
from src.shared.embedding import get_embedding
from src.shared.errors import BadRequestError, ConflictError, NotFoundError
from src.shared.schemas import PaginatedResponse, PaginationParams

from . import search as search_engine
from .models import Article, ArticleEmbedding, Digest
from .schemas import (
    AnnotationCreate,
    AnnotationResponse,
    ArticleCreate,
    ArticleResponse,
    ArticleUpdate,
    DashboardResponse,
    DigestResponse,
    PaperSearchResult,
    SearchRequest,
)
from .services import (
    annotation_service,
    article_service,
    dashboard_service,
    digest_service,
)

logger = logging.getLogger(__name__)

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
    _user: dict = require_permission("paper.read"),
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
async def get_article(
    article_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("paper.read"),
):
    instance = await article_service.get(db, article_id)
    if not instance:
        raise NotFoundError("Article not found", code="paper.article_not_found")
    return article_service.to_response(instance)


@router.post("/articles", response_model=ArticleResponse, status_code=201)
async def create_article(
    body: ArticleCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("paper.write"),
):
    # Dedup by arxiv_id
    if body.arxiv_id:
        existing = await article_service.get_by_arxiv_id(db, body.arxiv_id)
        if existing:
            raise ConflictError(
                f"Article with arxiv_id={body.arxiv_id} already exists",
                code="paper.arxiv_id_conflict",
            )

    # Dedup by doi
    if body.doi:
        existing = await article_service.get_by_doi(db, body.doi)
        if existing:
            raise ConflictError(
                f"Article with doi={body.doi} already exists",
                code="paper.doi_conflict",
            )

    instance = await article_service.create(db, space_id, body)

    # Generate embedding (best-effort — never block article creation)
    try:
        embed_text = f"{instance.title} {instance.abstract or ''}"
        embedding = await get_embedding(embed_text)
        if embedding:
            instance.embedding = embedding
            db.add(ArticleEmbedding(article_id=instance.id, embedding=embedding))
    except Exception:
        logger.warning("Failed to generate embedding for article %s", instance.id, exc_info=True)

    await db.commit()
    await db.refresh(instance)
    return article_service.to_response(instance)


@router.put("/articles/{article_id}", response_model=ArticleResponse)
async def update_article(
    article_id: str,
    body: ArticleUpdate,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("paper.write"),
):
    instance = await article_service.update(db, article_id, body)
    if not instance:
        raise NotFoundError("Article not found", code="paper.article_not_found")
    await db.commit()
    await db.refresh(instance)
    return article_service.to_response(instance)


@router.delete("/articles/{article_id}", status_code=204)
async def delete_article(
    article_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("paper.write"),
):
    deleted = await article_service.delete(db, article_id)
    if not deleted:
        raise NotFoundError("Article not found", code="paper.article_not_found")
    await db.commit()


# ======================== Search ========================


@router.post("/search", response_model=list[PaperSearchResult])
async def search_articles(
    body: SearchRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("paper.read"),
):
    return await search_engine.search_articles(db, space_id, body)


# ======================== Digest ========================


async def _bg_generate_digest(article_id: str, space_id: str, model_name: str | None = None) -> None:
    """Background task: generate (or regenerate) digest for one article.

    Pulls a fresh DB session, calls generate_digest(), then upserts the result.
    model_name is informational — actual model is resolved inside digest_generator.
    """
    from src.shared.database import async_session_factory

    from .digest_generator import generate_digest
    from .schemas import DigestCreate

    try:
        async with async_session_factory() as db:
            article = await article_service.get(db, article_id)
            if not article or not article.abstract:
                logger.warning("_bg_generate_digest: article %s missing or no abstract", article_id)
                return

            digest_data = await generate_digest(
                title=article.title,
                abstract=article.abstract,
                arxiv_id=article.arxiv_id,
            )
            if digest_data is None:
                logger.warning("_bg_generate_digest: generate_digest returned None for %s", article_id)
                return

            now = datetime.now(UTC)
            create = DigestCreate(
                paper_id=article_id,
                one_liner=digest_data.get("one_liner"),
                key_findings=digest_data.get("key_findings", []),
                workshop_relevance=digest_data.get("workshop_relevance"),
                applicable_modules=digest_data.get("applicable_modules", []),
                actionable_insight=digest_data.get("actionable_insight"),
                effort_estimate=digest_data.get("effort_estimate"),
                confidence=digest_data.get("confidence"),
                model_used=digest_data.get("model_used"),
                generated_at=now,
            )
            await digest_service.upsert(db, space_id, article_id, create)
            await db.commit()
            logger.info("_bg_generate_digest: digest saved for article %s", article_id)
    except Exception:
        logger.exception("_bg_generate_digest: failed for article %s", article_id)


@router.get("/articles/{article_id}/digest", response_model=DigestResponse)
async def get_digest(
    article_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("paper.read"),
):
    article = await article_service.get(db, article_id)
    if not article:
        raise NotFoundError("Article not found", code="paper.article_not_found")

    digest = await digest_service.get_by_paper_id(db, article_id)
    if not digest:
        raise NotFoundError("Digest not found", code="paper.digest_not_found")
    return digest_service.to_response(digest)


@router.post("/articles/{article_id}/digest/trigger", status_code=202)
async def trigger_digest(
    article_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("paper.write"),
):
    """Trigger async digest generation for an article.

    Returns 202 immediately. Digest generation runs in background.
    Phase 3 will implement the actual LLM digest_generator.
    For now, returns a placeholder indicating the job is queued.
    """
    article = await article_service.get(db, article_id)
    if not article:
        raise NotFoundError("Article not found", code="paper.article_not_found")

    # Phase 3: background_tasks.add_task(generate_digest, article_id, space_id)
    return {
        "article_id": article_id,
        "status": "queued",
        "message": "Digest generation queued. Check back shortly.",
    }


# ======================== Annotations ========================


@router.get(
    "/articles/{article_id}/annotations",
    response_model=PaginatedResponse[AnnotationResponse],
)
async def list_annotations(
    article_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("paper.read"),
):
    article = await article_service.get(db, article_id)
    if not article:
        raise NotFoundError("Article not found", code="paper.article_not_found")

    pagination = PaginationParams(page=page, page_size=page_size)
    return await annotation_service.list_by_paper(db, article_id, pagination)


@router.post(
    "/articles/{article_id}/annotations",
    response_model=AnnotationResponse,
    status_code=201,
)
async def create_annotation(
    article_id: str,
    body: AnnotationCreate,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("paper.write"),
):
    article = await article_service.get(db, article_id)
    if not article:
        raise NotFoundError("Article not found", code="paper.article_not_found")

    instance = await annotation_service.create_for_paper(db, space_id, article_id, body)
    await db.commit()
    await db.refresh(instance)
    return annotation_service.to_response(instance)


# ======================== Batch Redigest ========================


class RedigestRequest(BaseModel):
    model_name: str | None = None
    relevance_filter: str | None = None  # "high" | "medium" | "low" | null


@router.post("/digest/redigest", status_code=202)
async def batch_redigest(
    body: RedigestRequest,
    background_tasks: BackgroundTasks,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("paper.write"),
):
    """Batch re-generate digests for articles, optionally filtered by existing digest relevance.

    Queues background digest regeneration for each article that has an abstract.
    If relevance_filter is set, only articles whose existing digest matches that
    workshop_relevance level are included.

    Returns 202 with the count of queued items.
    """
    if body.relevance_filter is not None:
        # Only articles that already have a digest with matching relevance
        q = (
            select(Article)
            .join(Digest, Digest.paper_id == Article.id)
            .where(
                Article.space_id == space_id,
                Article.deleted_at == None,  # noqa: E711
                Article.abstract != None,  # noqa: E711
                Digest.workshop_relevance == body.relevance_filter,
                Digest.deleted_at == None,  # noqa: E711
            )
        )
    else:
        # All articles with an abstract
        q = select(Article).where(
            Article.space_id == space_id,
            Article.deleted_at == None,  # noqa: E711
            Article.abstract != None,  # noqa: E711
        )

    rows = (await db.execute(q)).scalars().all()
    queued = 0
    for article in rows:
        background_tasks.add_task(_bg_generate_digest, article.id, space_id, body.model_name)
        queued += 1

    return {
        "status": "queued",
        "queued_count": queued,
        "relevance_filter": body.relevance_filter,
        "message": f"Digest regeneration queued for {queued} articles.",
    }


# ======================== Single arXiv Import ========================


class ArxivFetchRequest(BaseModel):
    arxiv_url_or_id: str


def _extract_arxiv_id(raw: str) -> str | None:
    """Extract bare arXiv ID from a URL or bare ID string.

    Handles:
      - "2401.12345"
      - "2401.12345v2"
      - "https://arxiv.org/abs/2401.12345"
      - "https://arxiv.org/abs/2401.12345v2"
      - "http://export.arxiv.org/abs/2401.12345"
    """
    raw = raw.strip()
    # Try to extract from URL path
    match = re.search(r"/abs/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", raw)
    if match:
        arxiv_id = match.group(1)
    elif re.fullmatch(r"[0-9]{4}\.[0-9]{4,5}(?:v\d+)?", raw):
        arxiv_id = raw
    else:
        return None
    # Strip version suffix for dedup key
    return arxiv_id.rsplit("v", 1)[0] if re.search(r"v\d+$", arxiv_id) else arxiv_id


def _fetch_single_arxiv_sync(arxiv_id: str) -> bytes | None:
    """Synchronous fetch of a single arXiv paper from the Atom API."""
    params = urllib.parse.urlencode({"id_list": arxiv_id})
    url = f"http://export.arxiv.org/api/query?{params}"
    logger.debug("fetch/arxiv: GET %s", url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Workshop/1.0 (paper module)"})  # noqa: S310
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.error("fetch/arxiv: HTTP error — %s", exc)
        return None


@router.post("/fetch/arxiv", response_model=ArticleResponse, status_code=201)
async def fetch_arxiv_paper(
    body: ArxivFetchRequest,
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("paper.write"),
):
    """Import a single paper from arXiv by URL or bare arXiv ID.

    Fetches metadata from the arXiv Atom API, deduplicates by arxiv_id,
    and creates an Article record. Returns the created article.
    """
    from .arxiv_fetcher import _parse_feed

    arxiv_id = _extract_arxiv_id(body.arxiv_url_or_id)
    if not arxiv_id:
        raise BadRequestError(
            f"Cannot parse arXiv ID from: {body.arxiv_url_or_id!r}",
            code="paper.invalid_arxiv_id",
        )

    # Dedup check
    existing = await article_service.get_by_arxiv_id(db, arxiv_id)
    if existing:
        raise ConflictError(
            f"Article with arxiv_id={arxiv_id} already exists",
            code="paper.arxiv_id_conflict",
        )

    # Fetch from arXiv API (network I/O in thread)
    xml_bytes = await asyncio.to_thread(_fetch_single_arxiv_sync, arxiv_id)
    if xml_bytes is None:
        raise BadRequestError(
            f"Failed to fetch arXiv paper {arxiv_id} — network error",
            code="paper.arxiv_fetch_failed",
        )

    papers = _parse_feed(xml_bytes)
    if not papers:
        raise NotFoundError(
            f"arXiv ID {arxiv_id} not found or returned no results",
            code="paper.arxiv_not_found",
        )

    paper = papers[0]

    # Build published year
    year = None
    published_str = paper.get("published", "")
    if published_str:
        try:
            year = datetime.fromisoformat(published_str).year
        except (ValueError, AttributeError):
            pass

    create = ArticleCreate(
        title=paper["title"],
        abstract=paper.get("abstract") or None,
        arxiv_id=paper.get("arxiv_id"),
        year=year,
        authors=[{"name": a} for a in paper.get("authors", [])],
        categories=paper.get("categories", []),
        pdf_url=paper.get("pdf_url") or None,
        source_url=paper.get("source_url") or None,
    )
    instance = await article_service.create(db, space_id, create)

    # Generate embedding (best-effort)
    try:
        embed_text = f"{instance.title} {instance.abstract or ''}"
        embedding = await get_embedding(embed_text)
        if embedding:
            instance.embedding = embedding
            db.add(ArticleEmbedding(article_id=instance.id, embedding=embedding))
    except Exception:
        logger.warning("fetch/arxiv: embedding failed for %s", arxiv_id, exc_info=True)

    await db.commit()
    await db.refresh(instance)
    return article_service.to_response(instance)


# ======================== Dashboard ========================


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    space_id: str = Query("default"),
    db: AsyncSession = Depends(get_db),
    _user: dict = require_permission("paper.read"),
):
    return await dashboard_service.get_summary(db, space_id)


# ======================== Status ========================


@router.get("/status")
async def paper_status():
    return {"module": "paper", "status": "active"}

"""arXiv Atom API fetcher for the paper module.

Fetches recent papers from specified categories, computes oMLX embedding
similarity against WATCH_TOPICS, and stores new papers (dedup by arxiv_id).

arXiv rate limit policy: 1 request per 3 seconds.
XML parsing uses stdlib xml.etree.ElementTree — no extra dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.scoring_stages import cosine_similarity

try:
    from sdk_client.retry import with_backoff as _with_backoff

    _HAS_RETRY = True
except ImportError:
    _HAS_RETRY = False

logger = logging.getLogger(__name__)

# ── Watch configuration ──────────────────────────────────────────────────────

WATCH_CATEGORIES = ["cs.IR", "cs.CL", "cs.AI", "cs.SE", "cs.MA"]

WATCH_TOPICS = [
    "retrieval augmented generation reranking",
    "AI agent orchestration tool use",
    "knowledge graph memory for LLM",
    "local LLM inference MLX quantization",
    "semantic search hybrid BM25 dense",
    "prompt engineering skill routing",
    "code generation evaluation",
    "workflow automation DAG",
]

# ── arXiv Atom API constants ─────────────────────────────────────────────────

_ARXIV_API_BASE = "http://export.arxiv.org/api/query"
_ARXIV_NS = "http://www.w3.org/2005/Atom"
_ARXIV_TERM_NS = "http://arxiv.org/schemas/atom"
_RATE_LIMIT_DELAY = 3.0  # seconds between requests (arXiv policy)
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB safety cap per response page

# XML namespaces for ElementTree
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


# ── arXiv API helpers ─────────────────────────────────────────────────────────


def _build_query(categories: list[str], days_back: int) -> str:
    """Build arXiv search query string for given categories and date window."""
    since = (datetime.now(UTC) - timedelta(days=days_back)).strftime("%Y%m%d%H%M")
    now = datetime.now(UTC).strftime("%Y%m%d%H%M")

    cat_query = " OR ".join(f"cat:{c}" for c in categories)
    date_filter = f"submittedDate:[{since} TO {now}]"
    return f"({cat_query}) AND {date_filter}"


def _parse_entry(entry: ET.Element) -> dict | None:
    """Parse a single arXiv Atom entry element into a paper dict."""
    try:
        # Title — strip whitespace/newlines
        title_el = entry.find("atom:title", _NS)
        title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""

        # Abstract
        summary_el = entry.find("atom:summary", _NS)
        abstract = (summary_el.text or "").strip() if summary_el is not None else ""

        # arXiv ID — strip URL prefix
        id_el = entry.find("atom:id", _NS)
        raw_id = (id_el.text or "").strip() if id_el is not None else ""
        # raw_id is like http://arxiv.org/abs/2301.12345v1
        arxiv_id = raw_id.split("/abs/")[-1].rsplit("v", 1)[0] if "/abs/" in raw_id else raw_id

        # PDF URL
        pdf_url = ""
        source_url = raw_id  # canonical page URL
        for link_el in entry.findall("atom:link", _NS):
            if link_el.get("type") == "application/pdf":
                pdf_url = link_el.get("href", "")
                break

        # Authors
        authors = []
        for author_el in entry.findall("atom:author", _NS):
            name_el = author_el.find("atom:name", _NS)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        # Categories (primary + cross-listed)
        categories_list = []
        primary_cat_el = entry.find("arxiv:primary_category", _NS)
        if primary_cat_el is not None:
            primary = primary_cat_el.get("term", "")
            if primary:
                categories_list.append(primary)
        for cat_el in entry.findall("atom:category", _NS):
            term = cat_el.get("term", "")
            if term and term not in categories_list:
                categories_list.append(term)

        # Published date
        published_el = entry.find("atom:published", _NS)
        published_str = (published_el.text or "").strip() if published_el is not None else ""
        try:
            published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            published = datetime.now(UTC)

        if not arxiv_id or not title:
            logger.warning("arxiv_fetcher: skipping entry missing id/title")
            return None

        return {
            "title": title,
            "abstract": abstract,
            "arxiv_id": arxiv_id,
            "authors": authors,
            "categories": categories_list,
            "pdf_url": pdf_url,
            "source_url": source_url,
            "published": published.isoformat(),
        }
    except Exception as exc:
        logger.warning("arxiv_fetcher: failed to parse entry — %s", exc)
        return None


def _parse_feed(xml_bytes: bytes) -> list[dict]:
    """Parse arXiv Atom feed XML, return list of paper dicts."""
    try:
        root = ET.fromstring(xml_bytes)  # noqa: S314 — arXiv API trusted
    except ET.ParseError as exc:
        logger.error("arxiv_fetcher: XML parse error — %s", exc)
        return []

    papers = []
    for entry in root.findall("atom:entry", _NS):
        paper = _parse_entry(entry)
        if paper:
            papers.append(paper)
    return papers


def _fetch_arxiv_page_once(url: str) -> bytes:
    """Single HTTP GET to arXiv Atom API (no retry).

    Raises ``ValueError`` if the response body exceeds ``_MAX_RESPONSE_BYTES``
    to prevent memory exhaustion from unexpectedly large payloads.
    """
    req = urllib.request.Request(  # noqa: S310 — arXiv API only
        url, headers={"User-Agent": "Workshop/1.0 (paper module)"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        # Reject suspiciously large responses before reading into memory
        content_length = resp.headers.get("Content-Length")
        if content_length is not None and int(content_length) > _MAX_RESPONSE_BYTES:
            raise ValueError(
                f"arxiv response Content-Length {content_length} exceeds "
                f"{_MAX_RESPONSE_BYTES} byte limit"
            )
        # Read in chunks to enforce the limit even when Content-Length is absent
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = resp.read(65536)  # 64 KiB chunks
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_RESPONSE_BYTES:
                raise ValueError(
                    f"arxiv response body exceeded {_MAX_RESPONSE_BYTES} byte limit "
                    f"(read {total} bytes so far)"
                )
            chunks.append(chunk)
        return b"".join(chunks)


def _fetch_arxiv_page_sync(
    query: str,
    start: int,
    max_results: int,
) -> bytes | None:
    """Synchronous HTTP GET to arXiv Atom API. Called via asyncio.to_thread.

    Retries up to 3 times with exponential backoff on transient errors.
    _RATE_LIMIT_DELAY is preserved in the caller (fetch_arxiv_papers) for API politeness.
    """
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": start,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    url = f"{_ARXIV_API_BASE}?{params}"
    logger.debug("arxiv_fetcher: GET %s", url)
    try:
        if _HAS_RETRY:
            return _with_backoff(
                max_retries=3,
                base_delay=2.0,
                max_delay=30.0,
                retryable=(urllib.error.URLError, TimeoutError, OSError),
            )(_fetch_arxiv_page_once)(url)
        else:
            return _fetch_arxiv_page_once(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.error("arxiv_fetcher: HTTP error — %s", exc)
        return None


# ── Public async API ──────────────────────────────────────────────────────────


async def fetch_arxiv_papers(
    categories: list[str] | None = None,
    max_results: int = 50,
    days_back: int = 1,
) -> list[dict]:
    """Fetch recent arXiv papers for the given categories.

    Respects arXiv rate limit: 1 request per 3 seconds.
    Uses pagination if max_results > 100 (arXiv page size limit).

    Args:
        categories: arXiv category codes (default: WATCH_CATEGORIES).
        max_results: Maximum total papers to return.
        days_back: How many days back to search (default: 1 = yesterday + today).

    Returns:
        List of paper dicts with: title, abstract, arxiv_id, authors,
        categories, pdf_url, source_url, published.
    """
    if categories is None:
        categories = WATCH_CATEGORIES

    query = _build_query(categories, days_back)
    page_size = min(max_results, 100)  # arXiv max per request
    papers: list[dict] = []
    start = 0
    last_request_time: float = 0.0

    while len(papers) < max_results:
        # Enforce rate limit
        elapsed = asyncio.get_event_loop().time() - last_request_time
        if elapsed < _RATE_LIMIT_DELAY and last_request_time > 0:
            await asyncio.sleep(_RATE_LIMIT_DELAY - elapsed)

        fetch_count = min(page_size, max_results - len(papers))
        xml_bytes = await asyncio.to_thread(_fetch_arxiv_page_sync, query, start, fetch_count)
        last_request_time = asyncio.get_event_loop().time()

        if xml_bytes is None:
            logger.warning("arxiv_fetcher: page fetch failed at start=%d", start)
            break

        page_papers = _parse_feed(xml_bytes)
        if not page_papers:
            logger.info("arxiv_fetcher: no more results at start=%d", start)
            break

        papers.extend(page_papers)
        start += len(page_papers)

        # If we got fewer than requested, we've exhausted results
        if len(page_papers) < fetch_count:
            break

    logger.info("arxiv_fetcher: fetched %d papers total", len(papers))
    return papers[:max_results]


# ── Relevance scoring ─────────────────────────────────────────────────────────


async def score_relevance(
    papers: list[dict],
    topics: list[str] | None = None,
) -> list[dict]:
    """Score each paper's relevance against WATCH_TOPICS using oMLX embeddings.

    Adds a 'relevance_score' field (0.0-1.0) to each paper dict.
    Papers are returned sorted by relevance_score descending.

    Falls back to 0.5 for all papers if embedding is unavailable.

    Args:
        papers: List of paper dicts from fetch_arxiv_papers().
        topics: Topics to score against (default: WATCH_TOPICS).

    Returns:
        Same papers list with 'relevance_score' added, sorted desc.
    """
    if not papers:
        return papers

    if topics is None:
        topics = WATCH_TOPICS

    # Import here to avoid circular imports at module load time
    try:
        from core.src.shared.embedding import get_embeddings_batch
    except ImportError:
        try:
            from ...shared.embedding import get_embeddings_batch
        except ImportError:
            logger.warning(
                "arxiv_fetcher: embedding module not available — defaulting scores to 0.5"
            )
            for paper in papers:
                paper["relevance_score"] = 0.5
            return papers

    # Embed all topics (batch for efficiency)
    logger.info("arxiv_fetcher: embedding %d topics", len(topics))
    topic_embeddings = await get_embeddings_batch(topics, task_type="search_query")

    # Filter out topics where embedding failed
    valid_topics = [
        (t, emb) for t, emb in zip(topics, topic_embeddings, strict=True) if emb is not None
    ]

    if not valid_topics:
        logger.warning("arxiv_fetcher: all topic embeddings failed — defaulting scores to 0.5")
        for paper in papers:
            paper["relevance_score"] = 0.5
        return sorted(papers, key=lambda p: p["relevance_score"], reverse=True)

    # Build text representation for each paper (title + abstract excerpt)
    paper_texts = [f"{p['title']}. {p['abstract'][:500]}" for p in papers]

    logger.info("arxiv_fetcher: embedding %d papers", len(papers))
    paper_embeddings = await get_embeddings_batch(paper_texts, task_type="search_document")

    for paper, paper_emb in zip(papers, paper_embeddings, strict=True):
        if paper_emb is None:
            paper["relevance_score"] = 0.0
            continue

        # Max similarity across all topics
        max_sim = max(cosine_similarity(paper_emb, topic_emb) for _, topic_emb in valid_topics)
        # Normalize: cosine similarity typically in [-1, 1] but embeddings usually [0, 1]
        paper["relevance_score"] = max(0.0, min(1.0, float(max_sim)))

    papers_sorted = sorted(papers, key=lambda p: p["relevance_score"], reverse=True)
    logger.info(
        "arxiv_fetcher: top relevance=%.3f, bottom=%.3f",
        papers_sorted[0]["relevance_score"] if papers_sorted else 0,
        papers_sorted[-1]["relevance_score"] if papers_sorted else 0,
    )
    return papers_sorted


# ── Database storage ──────────────────────────────────────────────────────────


async def store_new_papers(
    db: AsyncSession,
    space_id: str,
    papers: list[dict],
) -> tuple[int, int]:
    """Store papers in the database, deduplicating by arxiv_id.

    Args:
        db: SQLAlchemy async session.
        space_id: The space to associate new papers with.
        papers: List of paper dicts (from fetch_arxiv_papers + score_relevance).

    Returns:
        Tuple of (new_count, skipped_count).
    """
    if not papers:
        return 0, 0

    from sqlalchemy import text

    new_count = 0
    skipped_count = 0

    for paper in papers:
        arxiv_id = paper.get("arxiv_id", "")
        if not arxiv_id:
            skipped_count += 1
            continue

        # Check for existing paper by arxiv_id
        exists_query = text(
            "SELECT id FROM paper.articles"
            " WHERE arxiv_id = :arxiv_id AND deleted_at IS NULL LIMIT 1"
        )
        result = await db.execute(exists_query, {"arxiv_id": arxiv_id})
        if result.fetchone() is not None:
            skipped_count += 1
            logger.debug("arxiv_fetcher: skipping existing arxiv_id=%s", arxiv_id)
            continue

        # Insert new paper using raw SQL to avoid ORM model dependency at import time
        # (paper.models may not be imported yet during runner execution)
        import json as _json

        insert_query = text(
            """
            INSERT INTO paper.articles (
                id, space_id, created_by,
                title, abstract, arxiv_id,
                authors, categories, pdf_url, source_url,
                tags, relevance_score,
                created_at, updated_at
            ) VALUES (
                gen_random_uuid(), :space_id, :created_by,
                :title, :abstract, :arxiv_id,
                :authors::jsonb, :categories::text[], :pdf_url, :source_url,
                :tags::text[], :relevance_score,
                NOW(), NOW()
            )
            """
        )

        tags = []
        relevance = paper.get("relevance_score", 0.0)
        if relevance >= 0.7:
            tags.append("high-relevance")
        elif relevance >= 0.4:
            tags.append("medium-relevance")

        try:
            await db.execute(
                insert_query,
                {
                    "space_id": space_id,
                    "created_by": "system",
                    "title": paper["title"],
                    "abstract": paper["abstract"],
                    "arxiv_id": arxiv_id,
                    "authors": _json.dumps(paper.get("authors", [])),
                    "categories": paper.get("categories", []),
                    "pdf_url": paper.get("pdf_url", ""),
                    "source_url": paper.get("source_url", ""),
                    "tags": tags,
                    "relevance_score": relevance,
                },
            )
            new_count += 1
            logger.debug("arxiv_fetcher: stored arxiv_id=%s score=%.3f", arxiv_id, relevance)
        except Exception as exc:
            logger.error("arxiv_fetcher: insert failed for %s — %s", arxiv_id, exc)
            skipped_count += 1
            await db.rollback()
            continue

    try:
        await db.commit()
    except Exception as exc:
        logger.error("arxiv_fetcher: commit failed — %s", exc)
        await db.rollback()
        return 0, len(papers)

    logger.info(
        "arxiv_fetcher: stored %d new, skipped %d existing",
        new_count,
        skipped_count,
    )
    return new_count, skipped_count

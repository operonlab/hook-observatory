"""WebCrawl service for intelflow — create reports from web URLs.

Uses crawl4ai_bridge to crawl pages, then creates intelflow reports
with the extracted content.

See AD-12 in docs/architecture/architecture-decisions.md.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.rate_limiter import RateLimiter
from src.shared.ssrf_guard import validate_url

logger = logging.getLogger(__name__)

_limiter = RateLimiter(base_delay=(0.5, 1.5), max_delay=30.0)


async def create_report_from_url(
    url: str,
    *,
    db: AsyncSession,
    space_id: str,
    created_by: str | None = None,
    tags: list[str] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Crawl a URL and create an intelflow report from the content.

    Returns dict with report_id and crawl metadata.
    """
    from workshop.crawl4ai_bridge import crawl_url

    from .schemas import ReportCreate
    from .services import report_service

    # 0. SSRF guard — reject internal/private network targets
    validate_url(url)

    # 1. Crawl (rate-limited per domain)
    await _limiter.acquire(url)
    result = await crawl_url(url, timeout=90.0)
    if result.success:
        _limiter.report_success(url)
    else:
        _limiter.report_failure(url, 429)  # treat crawl failure as rate-limit signal
        return {"success": False, "error": result.error, "url": url}

    # 2. Build report content
    report_title = title or result.title or f"Web Crawl: {url}"
    content = f"# {report_title}\n\nSource: {url}\n\n{result.markdown}"

    # 3. Create report via intelflow service
    data = ReportCreate(
        title=report_title,
        query=url,
        content=content[:100000],  # cap at 100k chars
        sources=[{"url": url, "title": result.title}],
        tags=tags or ["webcrawl"],
        skill_name="webcrawl",
    )
    report = await report_service.create(db, space_id, data, user_id=created_by)

    return {
        "success": True,
        "report_id": report.id,
        "title": report_title,
        "url": url,
        "content_length": len(result.markdown),
        "links_found": len(result.links),
    }

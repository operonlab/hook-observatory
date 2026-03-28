"""WebCrawl service for intelflow — create reports from web URLs.

Uses crawl4ai_bridge to crawl pages, then creates intelflow reports
with the extracted content.

See AD-12 in docs/architecture/architecture-decisions.md.
"""

from __future__ import annotations

import asyncio
import logging
import random
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
    from sdk_client.crawl4ai_bridge import crawl_url

    from .schemas import ReportCreate
    from .services import report_service

    # 0. SSRF guard — reject internal/private network targets
    validate_url(url)

    # 1. Crawl (rate-limited per domain, with exponential backoff retry)
    await _limiter.acquire(url)
    result = None
    _crawl_max_retries = 3
    for _attempt in range(_crawl_max_retries):
        result = await crawl_url(url, timeout=90.0)
        if result.success:
            _limiter.report_success(url)
            break
        # Retry on transient failures; permanent failures (e.g. 404) don't benefit from retry
        _is_transient = result.error and any(
            kw in str(result.error).lower()
            for kw in ("timeout", "connection", "network", "reset", "refused")
        )
        if not _is_transient or _attempt == _crawl_max_retries - 1:
            _limiter.report_failure(url, 429)
            return {"success": False, "error": result.error, "url": url}
        _delay = min(2.0 * (2**_attempt), 30.0) + random.uniform(0, 1)
        logger.warning("crawl retry %d/%d for %s in %.1fs: %s", _attempt + 1, _crawl_max_retries, url, _delay, result.error)
        await asyncio.sleep(_delay)

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

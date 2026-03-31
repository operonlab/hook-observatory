"""WebCrawl capture adapter — capture URLs for web crawling and report creation.

Users can quick-capture a URL ("記下這個網頁"), then promote to
create an intelflow report via crawl4ai extraction.

See AD-12 in docs/architecture/architecture-decisions.md.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .adapters import BaseCaptureAdapter
from .strategies import LLMEnrichmentStrategy, PatternMatchStrategy


class WebCrawlCaptureAdapter(BaseCaptureAdapter):
    """Capture a web URL for later crawling and report creation."""

    module = "intelflow"
    entity_type = "webcrawl"

    field_weights = {
        "url": 60,  # required: the URL to crawl
        "title": 20,  # optional: user-provided title override
        "tags": 20,  # optional: tags for the report
    }

    default_values = {
        "tags": ["webcrawl"],
    }

    default_ttl_days = 7  # URLs are time-sensitive

    enrichment_adapter_type = "webcrawl"

    # Extract page title from raw HTML if captured via paste/clipboard
    @property
    def enrichment_strategies(self):
        from .enrichment_config import ENRICHMENT_SCHEMAS, get_enrichment_profile

        schema = ENRICHMENT_SCHEMAS.get(("intelflow", "webcrawl"))
        strategies = [PatternMatchStrategy(patterns={"title": r"<title>([^<]+)</title>"})]
        if schema:
            profile = get_enrichment_profile(self.enrichment_adapter_type)
            strategies.append(
                LLMEnrichmentStrategy(
                    field_schema=schema,
                    min_completeness=profile["min_completeness"],
                )
            )
        return strategies

    def smart_defaults(self, payload: dict[str, Any], user_prefs: dict[str, Any]) -> dict[str, Any]:
        result = {**self.default_values, **payload}

        # Auto-extract domain as tag if no tags provided
        url = result.get("url", "")
        if url and not payload.get("tags"):
            from urllib.parse import urlparse

            try:
                domain = urlparse(url).netloc.replace("www.", "")
                result["tags"] = ["webcrawl", domain]
            except Exception:  # noqa: S110
                pass

        return result

    async def promote(
        self,
        payload: dict[str, Any],
        db: AsyncSession,
        space_id: str,
        created_by: str | None,
    ) -> str:
        """Promote by crawling the URL and creating an intelflow report."""
        url = payload.get("url")
        if not url:
            from src.shared.errors import BadRequestError

            raise BadRequestError("URL is required for webcrawl capture")

        from src.shared.ssrf_guard import validate_url

        validate_url(url)

        from src.modules.intelflow.webcrawl import create_report_from_url

        result = await create_report_from_url(
            url,
            db=db,
            space_id=space_id,
            created_by=created_by,
            tags=payload.get("tags", ["webcrawl"]),
            title=payload.get("title"),
        )

        if not result.get("success"):
            from src.shared.errors import BadRequestError

            raise BadRequestError(f"Crawl failed: {result.get('error', 'unknown')}")

        return result["report_id"]


ADAPTERS: list[BaseCaptureAdapter] = [WebCrawlCaptureAdapter()]

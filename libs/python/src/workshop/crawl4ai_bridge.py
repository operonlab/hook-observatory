"""Crawl4AI bridge — subprocess JSON protocol to isolated venv.

Workshop main venv calls crawl4ai in ~/.venvs/crawl4ai via subprocess.
See AD-12 in docs/architecture/architecture-decisions.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CRAWL4AI_PYTHON = str(Path("~/.venvs/crawl4ai/bin/python").expanduser())


@dataclass
class CrawlResult:
    """Structured result from a web crawl."""

    url: str
    markdown: str = ""
    title: str = ""
    links: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str = ""


async def crawl_url(
    url: str,
    *,
    extract_schema: dict[str, Any] | None = None,
    timeout: float = 60.0,  # noqa: ASYNC109
) -> CrawlResult:
    """Crawl a URL using crawl4ai in the isolated venv.

    Args:
        url: The URL to crawl
        extract_schema: Optional JSON schema for LLM extraction
        timeout: Process timeout in seconds
    """
    python_path = CRAWL4AI_PYTHON

    # Build the crawl4ai script to execute
    script = """
import asyncio, json, sys
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig

async def main():
    request = json.loads(sys.stdin.read())
    url = request["url"]
    config = CrawlerRunConfig(
        markdown_generator=None,  # use default
        verbose=False,
    )
    browser_config = BrowserConfig(headless=True, verbose=False)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=config)
        output = {
            "url": url,
            "markdown": result.markdown[:50000] if result.markdown else "",
            "title": result.metadata.get("title", "") if result.metadata else "",
            "links": (
                [l.get("href", "") for l in (
                    result.links.get("internal", []) + result.links.get("external", [])
                )[:100]] if result.links else []
            ),
            "metadata": {k: str(v)[:500] for k, v in (result.metadata or {}).items()},
            "success": result.success,
            "error": result.error_message or "",
        }
        print(json.dumps(output))

asyncio.run(main())
"""

    request_json = json.dumps({"url": url, "extract_schema": extract_schema})

    try:
        proc = await asyncio.create_subprocess_exec(
            python_path,
            "-c",
            script,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=request_json.encode()),
            timeout=timeout,
        )

        if proc.returncode != 0:
            error_msg = stderr.decode().strip()[-500:]
            logger.error("crawl4ai_bridge_error: %s", error_msg)
            return CrawlResult(url=url, success=False, error=error_msg)

        data = json.loads(stdout.decode())
        return CrawlResult(**data)

    except TimeoutError:
        return CrawlResult(url=url, success=False, error=f"timeout after {timeout}s")
    except Exception as e:
        return CrawlResult(url=url, success=False, error=str(e))


async def crawl_batch(
    urls: list[str],
    *,
    max_concurrent: int = 3,
    timeout: float = 60.0,  # noqa: ASYNC109
) -> list[CrawlResult]:
    """Crawl multiple URLs with concurrency control."""
    sem = asyncio.Semaphore(max_concurrent)

    async def _crawl(url: str) -> CrawlResult:
        async with sem:
            return await crawl_url(url, timeout=timeout)

    return await asyncio.gather(*[_crawl(u) for u in urls])

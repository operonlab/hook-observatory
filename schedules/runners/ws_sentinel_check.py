#!/usr/bin/env python3
"""
ws_sentinel_check.py — Scheduled light health check (replaces persistent sentinel)

Runs all light checks, persists to sentinel DB, sends Bark on unhealthy.
Designed for Cronicle every-5-min schedule.
"""

import asyncio
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Allow importing from sentinel station
SENTINEL_DIR = Path.home() / "workshop/stations/sentinel"
sys.path.insert(0, str(SENTINEL_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sentinel-check")

BARK_URL = os.environ.get("BARK_URL", "http://127.0.0.1:8090")
BARK_KEY = os.environ.get("BARK_KEY", "")


async def _bark_notify(title: str, body: str, level: str = "active") -> None:
    """Best-effort Bark push notification."""
    if not BARK_KEY:
        return
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{BARK_URL}/{BARK_KEY}",
                json={"title": title, "body": body, "level": level, "group": "sentinel"},
            )
    except Exception:
        logger.warning("Bark notification failed")


async def main() -> None:
    from checker import run_all_light_checks
    from database import async_session, engine
    from models import Base
    from sqlalchemy import text

    # Ensure schema + tables
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS sentinel"))
        await conn.run_sync(Base.metadata.create_all)

    results = await run_all_light_checks()

    healthy = []
    unhealthy = []
    skipped = []

    for r in results:
        if r.status == "healthy":
            healthy.append(r.service)
        elif r.status == "skipped":
            skipped.append(r.service)
        else:
            unhealthy.append(r)

    # Persist all results
    async with async_session() as session:
        for r in results:
            await session.execute(
                text(
                    "INSERT INTO sentinel.health_checks"
                    " (id, service, check_type, status, response_ms, detail, created_at)"
                    " VALUES (:id, :service, :check_type, :status, :response_ms, :detail, :created_at)"
                ),
                {
                    "id": uuid.uuid4().hex[:16],
                    "service": r.service,
                    "check_type": r.check_type,
                    "status": r.status,
                    "response_ms": r.response_ms,
                    "detail": r.detail or None,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
        await session.commit()

    logger.info(
        "Check done: %d healthy, %d unhealthy, %d skipped",
        len(healthy),
        len(unhealthy),
        len(skipped),
    )

    # Notify on failures
    if unhealthy:
        names = ", ".join(r.service for r in unhealthy)
        logger.warning("Unhealthy: %s", names)
        await _bark_notify(
            title=f"Sentinel: {len(unhealthy)} service(s) down",
            body=names,
            level="timeSensitive",
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

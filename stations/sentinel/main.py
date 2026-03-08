"""Workshop Sentinel — Self-healing health monitoring station."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from checker import (
    CheckResult,
    run_all_deep_checks,
    run_all_light_checks,
)
from database import async_session, drain_spool_loop, engine, persist
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from models import Base
from remediation import Remediator
from sqlalchemy import text
from state import InterventionEngine, State

from config import config  # isort: skip
from push_notify import publish_push  # isort: skip
from routes import router, set_engine  # isort: skip

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sentinel")

# ── Global State ──

intervention_engine = InterventionEngine()
remediator = Remediator()

_light_task: asyncio.Task | None = None
_deep_task: asyncio.Task | None = None
_spool_task: asyncio.Task | None = None
_repair_task: asyncio.Task | None = None


# ── Background Loops ──


async def _persist_check(result: CheckResult) -> None:
    """Persist a health check result to DB."""
    await persist(
        "health_checks",
        {
            "id": uuid.uuid4().hex[:16],
            "service": result.service,
            "check_type": result.check_type,
            "status": result.status,
            "response_ms": result.response_ms,
            "detail": result.detail or None,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )


async def _light_check_loop() -> None:
    """Run light checks every 30s."""
    await asyncio.sleep(5)  # Initial delay for startup
    while True:
        try:
            results = await run_all_light_checks()
            for r in results:
                intervention_engine.update_light(r.service, r.status, r.response_ms)
                await _persist_check(r)

            healthy = sum(1 for r in results if r.status == "healthy")
            logger.info("Light check: %d/%d healthy", healthy, len(results))

            # Clean up expired locks for virtual services not in check lists
            intervention_engine.sweep_expired_locks()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Light check loop error")

        await asyncio.sleep(config.check.light_interval)


async def _deep_check_loop() -> None:
    """Run deep checks every 5 min."""
    await asyncio.sleep(30)  # Initial delay
    while True:
        try:
            results = await run_all_deep_checks()
            for r in results:
                intervention_engine.update_deep(r.service, r.status)
                await _persist_check(r)

            healthy = sum(1 for r in results if r.status == "healthy")
            logger.info("Deep check: %d/%d healthy", healthy, len(results))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Deep check loop error")

        await asyncio.sleep(config.check.deep_interval)


async def _repair_monitor_loop() -> None:
    """Monitor intervention states and dispatch repairs."""
    await asyncio.sleep(10)
    while True:
        try:
            for service, tracker in list(intervention_engine.trackers.items()):
                # Check active repairs
                if tracker.state == State.REPAIRING:
                    result = await remediator.check_completion(service)
                    if result and result != "running":
                        success = result == "success"
                        intervention_engine.set_repair_done(service, success)

                        # Record incident resolution
                        if tracker.incident_id:
                            try:
                                async with async_session() as session:
                                    update_sql = (
                                        "UPDATE sentinel.incidents"
                                        " SET status = :status,"
                                        " resolved_at = :resolved,"
                                        " repair_result = :result"
                                        " WHERE id = :id"
                                    )
                                    await session.execute(
                                        text(update_sql),
                                        {
                                            "status": "resolved" if success else "escalated",
                                            "resolved": datetime.now(UTC).isoformat(),
                                            "result": f'{{"auto_repair": "{result}"}}',
                                            "id": tracker.incident_id,
                                        },
                                    )
                                    await session.commit()
                            except Exception:
                                pass

                        # Push notification for repair result
                        if success:
                            await publish_push(
                                title=f"{service} 已修復",
                                body="自動修復成功完成",
                                severity="info",
                                tag=f"sentinel-{service}",
                            )
                        else:
                            await publish_push(
                                title=f"{service} 修復失敗 — 需人工介入",
                                body="自動修復未能解決問題",
                                severity="critical",
                                tag=f"sentinel-{service}",
                            )

                # Dispatch repair if needed
                elif tracker.state == State.INTERVENING:
                    detail = f"light={tracker.light_status}, deep={tracker.deep_status}"

                    # Create incident
                    inc_id = uuid.uuid4().hex[:16]
                    now = datetime.now(UTC).isoformat()
                    await persist(
                        "incidents",
                        {
                            "id": inc_id,
                            "service": service,
                            "status": "investigating",
                            "severity": "major"
                            if tracker.light_status in ("unhealthy", "timeout")
                            else "minor",
                            "title": f"Auto-detected: {service} unhealthy",
                            "detail": detail,
                            "created_at": now,
                        },
                    )
                    tracker.incident_id = inc_id

                    # Push notification: incident detected
                    sev = "major" if tracker.light_status in ("unhealthy", "timeout") else "minor"
                    await publish_push(
                        title=f"{service} 服務異常",
                        body=detail,
                        severity="critical" if sev == "major" else "warning",
                        tag=f"sentinel-{service}",
                    )

                    # Layer 1: Try simple restart first (fast, no AI)
                    from remediation import SimpleRestarter

                    _simple = SimpleRestarter()
                    if _simple.can_restart(service):
                        logger.info("Attempting simple restart for %s", service)
                        restarted = await _simple.try_restart(service)
                        if restarted:
                            # Wait for health check to confirm
                            await asyncio.sleep(10)
                            from checker import LIGHT_CHECKS, run_light_check

                            check = next((c for c in LIGHT_CHECKS if c.name == service), None)
                            if check:
                                result = await run_light_check(check)
                                if result.status == "healthy":
                                    intervention_engine.set_repair_done(service, True)
                                    await publish_push(
                                        title=f"{service} 已修復（簡單重啟）",
                                        body="直接重啟成功，無需 AI 介入",
                                        severity="info",
                                        tag=f"sentinel-{service}",
                                    )
                                    continue
                        logger.warning(
                            "Simple restart insufficient for %s, escalating to AI repair", service
                        )

                    # Layer 2: AI repair via tmux-relay (fallback)
                    pane = await remediator.dispatch(service, detail)
                    if pane:
                        intervention_engine.set_repairing(service, pane)

                        # Notify subscribers
                        try:
                            async with async_session() as session:
                                from models import Subscription
                                from sqlalchemy import select as sa_select

                                subs_result = await session.execute(
                                    sa_select(Subscription).where(Subscription.active.is_(True))
                                )
                                subs = [
                                    {"url": s.url, "events": s.events}
                                    for s in subs_result.scalars()
                                ]

                            if subs:
                                from notify import broadcast_incident

                                await broadcast_incident(
                                    subs,
                                    {
                                        "id": inc_id,
                                        "service": service,
                                        "severity": "major",
                                        "status": "repairing",
                                        "title": f"Auto-repair dispatched: {service}",
                                    },
                                )
                        except Exception:
                            pass
                    else:
                        # Can't get pane, escalate
                        intervention_engine.set_repair_done(service, False)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Repair monitor error")

        await asyncio.sleep(15)


# ── Lifespan ──


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create schema + tables, start background loops."""
    global _light_task, _deep_task, _spool_task, _repair_task

    # Ensure schema exists
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE SCHEMA IF NOT EXISTS sentinel"))
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schema ready")
    except Exception:
        logger.warning("Database unavailable — running in spool-only mode")

    set_engine(engine)

    # Start background loops
    _light_task = asyncio.create_task(_light_check_loop())
    _deep_task = asyncio.create_task(_deep_check_loop())
    _spool_task = asyncio.create_task(drain_spool_loop())
    _repair_task = asyncio.create_task(_repair_monitor_loop())

    logger.info(
        "Sentinel started — light=%ds, deep=%ds",
        config.check.light_interval,
        config.check.deep_interval,
    )

    yield

    # Shutdown
    for task in (_light_task, _deep_task, _spool_task, _repair_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await engine.dispose()
    logger.info("Sentinel shutdown complete")


# ── App ──

app = FastAPI(
    title="Workshop Sentinel",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:4101",
        "https://workshop.joneshong.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Serve Status Page static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():

    @app.api_route("/", methods=["GET", "HEAD"])
    async def serve_index(request: Request):
        from starlette.responses import FileResponse, RedirectResponse

        cookie = request.cookies.get(config.session_cookie_name)
        if not cookie:
            return RedirectResponse(url=config.login_url, status_code=302)

        from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

        try:
            URLSafeTimedSerializer(config.secret_key).loads(cookie, max_age=config.session_max_age)
        except (BadSignature, SignatureExpired):
            return RedirectResponse(url=config.login_url, status_code=302)

        return FileResponse(static_dir / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=static_dir), name="static")


def cli():
    """Entry point for `uv run sentinel`."""
    import uvicorn

    uvicorn.run(
        "main:app",
        host=config.host,
        port=config.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    cli()

"""Workshop Sentinel — Self-healing health monitoring station."""

from __future__ import annotations

import asyncio
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
from fastapi.staticfiles import StaticFiles
from models import Base
from remediation import Remediator
from sqlalchemy import text
from state import InterventionEngine, State
from workshop.station_bootstrap import setup_cors, setup_logging

from config import config  # isort: skip
from push_notify import publish_push  # isort: skip
from routes import router, set_engine  # isort: skip

logger = setup_logging("sentinel")

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


def _build_status_payload() -> dict:
    """Build the same data shape as /api/sentinel/status for SSE broadcast."""
    statuses = intervention_engine.get_all_statuses()
    services = []
    for _name, s in statuses.items():
        services.append(
            {
                "service": s["service"],
                "status": s["status"],
                "group": s.get("group"),
                "light_status": s.get("light_status"),
                "deep_status": s.get("deep_status"),
                "last_check": s.get("last_check"),
                "response_ms": s.get("response_ms"),
            }
        )

    severity_order = {
        "major_outage": 4,
        "partial_outage": 3,
        "degraded": 2,
        "maintenance": 1,
        "operational": 0,
    }
    worst = max((severity_order.get(svc["status"], 0) for svc in services), default=0)
    overall_map = {
        0: "all_operational",
        1: "maintenance",
        2: "degraded",
        3: "partial_outage",
        4: "major_outage",
    }
    return {
        "status": overall_map.get(worst, "all_operational"),
        "services": services,
        "checked_at": datetime.now(UTC).isoformat(),
    }


async def _light_check_loop() -> None:
    """Run light checks every 30s."""
    from sse import sse_broadcast

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

            # Broadcast updated status to all SSE clients
            await sse_broadcast("status", _build_status_payload())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Light check loop error")

        await asyncio.sleep(config.check.light_interval)


async def _deep_check_loop() -> None:
    """Run deep checks every 5 min."""
    from sse import sse_broadcast

    await asyncio.sleep(30)  # Initial delay
    while True:
        try:
            results = await run_all_deep_checks()
            for r in results:
                intervention_engine.update_deep(r.service, r.status)
                await _persist_check(r)

            healthy = sum(1 for r in results if r.status == "healthy")
            logger.info("Deep check: %d/%d healthy", healthy, len(results))

            # Broadcast updated status to all SSE clients
            await sse_broadcast("status", _build_status_payload())
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
                            except Exception:  # noqa: S110
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
                    # Build detail with deep check info for richer diagnosis
                    detail_parts = []
                    if tracker.light_status and tracker.light_status != "healthy":
                        detail_parts.append(f"light={tracker.light_status}")
                    if tracker.deep_status and tracker.deep_status != "healthy":
                        detail_parts.append(f"deep={tracker.deep_status}")

                    # Include deep check detail message if available
                    from checker import DEEP_CHECKS

                    deep_detail = ""
                    check_url = ""
                    for dc in DEEP_CHECKS:
                        svc_name = dc.name.replace("-render", "")
                        if svc_name == service or dc.name == service:
                            check_url = dc.url
                            break

                    # Get the last deep check detail from persisted results
                    try:
                        async with async_session() as session:
                            row = await session.execute(
                                text(
                                    "SELECT detail FROM sentinel.health_checks"
                                    " WHERE service = :svc AND check_type = 'deep'"
                                    " AND detail IS NOT NULL AND detail != ''"
                                    " ORDER BY created_at DESC LIMIT 1"
                                ),
                                {
                                    "svc": service.replace("-render", "")
                                    if "-render" not in service
                                    else service
                                },
                            )
                            r = row.first()
                            if r:
                                deep_detail = r[0]
                                detail_parts.append(f"detail={deep_detail}")
                    except Exception:  # noqa: S110
                        pass

                    detail = ", ".join(detail_parts) if detail_parts else "unknown failure"

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

                    # ── Layer 1: Simple restart (fast, no code changes) ──
                    from remediation import FrontendRebuilder, SimpleRestarter

                    _simple = SimpleRestarter()
                    if _simple.can_restart(service):
                        logger.info("Layer 1: Attempting simple restart for %s", service)
                        restarted = await _simple.try_restart(service)
                        if restarted:
                            await asyncio.sleep(10)
                            from checker import LIGHT_CHECKS, run_light_check

                            check = next((c for c in LIGHT_CHECKS if c.name == service), None)
                            if check:
                                result = await run_light_check(check)
                                if result.status == "healthy":
                                    intervention_engine.set_repair_done(service, True)
                                    await publish_push(
                                        title=f"{service} 已修復（簡單重啟）",  # noqa: RUF001
                                        body="Layer 1: 直接重啟成功",
                                        severity="info",
                                        tag=f"sentinel-{service}",
                                    )
                                    continue
                        logger.warning("Layer 1 insufficient for %s", service)

                    # ── Layer 2: Frontend rebuild (for stale build issues) ──
                    _frontend = FrontendRebuilder()
                    if _frontend.can_rebuild(service):
                        logger.info("Layer 2: Attempting frontend rebuild for %s", service)
                        rebuilt = await _frontend.try_rebuild()
                        if rebuilt:
                            await asyncio.sleep(5)
                            # Re-run the deep check to see if rebuild fixed it
                            from checker import run_deep_check

                            dc = next(
                                (
                                    c
                                    for c in DEEP_CHECKS
                                    if c.name == service or c.name == f"{service}-render"
                                ),
                                None,
                            )
                            if dc:
                                result = await run_deep_check(dc)
                                if result.status == "healthy":
                                    intervention_engine.set_repair_done(service, True)
                                    await publish_push(
                                        title=f"{service} 已修復（前端重建）",  # noqa: RUF001
                                        body="Layer 2: pnpm build + nginx reload 成功",
                                        severity="info",
                                        tag=f"sentinel-{service}",
                                    )
                                    continue
                        logger.warning(
                            "Layer 2 insufficient for %s, escalating to AI repair", service
                        )

                    # ── Layer 3: AI repair via tmux-relay (code-level fix) ──
                    from prompt_templates import classify_failure

                    failure_category = classify_failure(deep_detail or detail)
                    logger.info(
                        "Layer 3: Dispatching AI repair for %s (category=%s)",
                        service,
                        failure_category,
                    )
                    pane = await remediator.dispatch(service, detail, url=check_url)
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
                                        "title": f"AI repair dispatched: {service} ({failure_category})",
                                    },
                                )
                        except Exception:  # noqa: S110
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

setup_cors(app, mode="restricted", extra_origins=[f"http://localhost:{config.port + 1}"])

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

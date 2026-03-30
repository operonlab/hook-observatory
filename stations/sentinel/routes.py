"""Sentinel API routes — 18 endpoints (11 sentinel + 7 sysmon proxy)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import httpx
from auth import require_auth
from database import get_session, persist
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from models import ActiveOperation, Incident, Subscription
from schemas import (
    ActiveOperationResponse,
    DayUptime,
    HealthResponse,
    IncidentListResponse,
    IncidentResponse,
    NotifyRequest,
    NotifyResponse,
    OverallStatus,
    ResolveRequest,
    ResolveResponse,
    ServiceStatus,
    ServiceUptime,
    SubscribeRequest,
    SubscribeResponse,
    UptimeResponse,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
log = logging.getLogger("sentinel")

SYSMON_BASE = "http://127.0.0.1:10102"

# Will be injected by main.py at startup
_engine = None


def set_engine(engine_ref):
    global _engine
    _engine = engine_ref


# ── GET /api/sentinel/health (public — used by other services) ──


@router.get("/api/sentinel/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok")


# ── GET /api/sentinel/status (auth required) ──


@router.get("/api/sentinel/status", response_model=OverallStatus)
async def overall_status(_user: dict = Depends(require_auth)):
    from main import intervention_engine

    statuses = intervention_engine.get_all_statuses()
    services = []
    for _name, s in statuses.items():
        services.append(
            ServiceStatus(
                service=s["service"],
                status=s["status"],
                group=s.get("group"),
                light_status=s.get("light_status"),
                deep_status=s.get("deep_status"),
                last_check=s.get("last_check"),
                response_ms=s.get("response_ms"),
            )
        )

    # Determine overall
    severity_order = {
        "major_outage": 4,
        "partial_outage": 3,
        "degraded": 2,
        "maintenance": 1,
        "operational": 0,
    }
    worst = max((severity_order.get(s.status, 0) for s in services), default=0)
    overall_map = {
        0: "all_operational",
        1: "maintenance",
        2: "degraded",
        3: "partial_outage",
        4: "major_outage",
    }

    return OverallStatus(
        status=overall_map.get(worst, "all_operational"),
        services=services,
        checked_at=datetime.now(UTC).isoformat(),
    )


# ── GET /api/sentinel/status/{service} (auth required) ──


@router.get("/api/sentinel/status/{service}", response_model=ServiceStatus)
async def service_status(service: str, _user: dict = Depends(require_auth)):
    from main import intervention_engine

    statuses = intervention_engine.get_all_statuses()
    s = statuses.get(service)
    if not s:
        return ServiceStatus(service=service, status="unknown")
    return ServiceStatus(
        service=s["service"],
        status=s["status"],
        group=s.get("group"),
        light_status=s.get("light_status"),
        deep_status=s.get("deep_status"),
        last_check=s.get("last_check"),
        response_ms=s.get("response_ms"),
    )


# ── POST /api/sentinel/notify (public — used by agents) ──


@router.post("/api/sentinel/notify", response_model=NotifyResponse)
async def notify_operation(req: NotifyRequest, db: AsyncSession = Depends(get_session)):
    from main import intervention_engine

    op_id = uuid.uuid4().hex[:16]
    now = datetime.now(UTC).isoformat()

    # Update state machine
    intervention_engine.notify_agent(req.service, req.agent_id, req.pid, req.estimated_duration)

    # Persist to DB (with spool fallback)
    await persist(
        "active_operations",
        {
            "id": op_id,
            "service": req.service,
            "action": req.action,
            "agent_id": req.agent_id,
            "pid": req.pid,
            "estimated_duration": req.estimated_duration,
            "created_at": now,
        },
    )

    return NotifyResponse(
        id=op_id, message=f"Acknowledged: {req.agent_id} working on {req.service}"
    )


# ── POST /api/sentinel/resolve (public — used by agents) ──


@router.post("/api/sentinel/resolve", response_model=ResolveResponse)
async def resolve_operation(req: ResolveRequest, db: AsyncSession = Depends(get_session)):
    from main import intervention_engine

    intervention_engine.resolve_agent(req.service, req.agent_id)

    # Find and close active operation
    try:
        result = await db.execute(
            select(ActiveOperation)
            .where(ActiveOperation.service == req.service)
            .where(ActiveOperation.agent_id == req.agent_id)
            .where(ActiveOperation.resolved_at.is_(None))
            .order_by(ActiveOperation.created_at.desc())
            .limit(1)
        )
        op = result.scalar_one_or_none()
        if op:
            op.resolved_at = datetime.now(UTC).isoformat()
            op.result = req.result
            await db.commit()
            return ResolveResponse(message="Resolved", operation_id=op.id)
    except Exception:  # noqa: S110
        pass

    return ResolveResponse(message="Resolved (no matching operation found)")


# ── GET /api/sentinel/incidents (auth required) ──


@router.get("/api/sentinel/incidents", response_model=IncidentListResponse)
async def list_incidents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    service: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
):
    try:
        # Build base query with optional filters
        base = select(Incident)
        count_base = select(func.count()).select_from(Incident)

        if status:
            base = base.where(Incident.status == status)
            count_base = count_base.where(Incident.status == status)
        if service:
            base = base.where(Incident.service == service)
            count_base = count_base.where(Incident.service == service)

        # Count
        count_result = await db.execute(count_base)
        total = count_result.scalar() or 0

        # Fetch
        result = await db.execute(
            base.order_by(Incident.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        incidents = result.scalars().all()

        return IncidentListResponse(
            items=[
                IncidentResponse(
                    id=i.id,
                    service=i.service,
                    status=i.status,
                    severity=i.severity,
                    title=i.title,
                    detail=i.detail,
                    created_at=i.created_at,
                    resolved_at=i.resolved_at,
                )
                for i in incidents
            ],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception:
        return IncidentListResponse(items=[], total=0, page=page, page_size=page_size)


# ── GET /api/sentinel/incidents/{id} (auth required) ──


@router.get("/api/sentinel/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(
    incident_id: str,
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
):
    from fastapi import HTTPException

    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    inc = result.scalar_one_or_none()
    if not inc:
        raise HTTPException(404, "Incident not found")
    return IncidentResponse(
        id=inc.id,
        service=inc.service,
        status=inc.status,
        severity=inc.severity,
        title=inc.title,
        detail=inc.detail,
        created_at=inc.created_at,
        resolved_at=inc.resolved_at,
    )


# ── GET /api/sentinel/uptime (auth required) ──


@router.get("/api/sentinel/uptime", response_model=UptimeResponse)
async def get_uptime(
    days: int = Query(90, ge=1, le=365),
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
):
    """Per-service per-day uptime percentage from health_checks table."""
    try:
        result = await db.execute(
            text("""
            SELECT
                service,
                created_at::date AS day,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'healthy') AS healthy
            FROM sentinel.health_checks
            WHERE created_at::date >= (CURRENT_DATE - :days * INTERVAL '1 day')
            GROUP BY service, day
            ORDER BY service, day
        """),
            {"days": days},
        )
        rows = result.fetchall()

        service_data: dict[str, list[DayUptime]] = {}
        for row in rows:
            svc = row[0]
            day = str(row[1])
            total = row[2]
            healthy = row[3]
            pct = round(healthy / total * 100, 2) if total > 0 else 0
            status = "operational" if pct >= 99 else "degraded" if pct >= 90 else "outage"

            if svc not in service_data:
                service_data[svc] = []
            service_data[svc].append(DayUptime(date=day, uptime_pct=pct, status=status))

        return UptimeResponse(
            services=[ServiceUptime(service=k, days=v) for k, v in service_data.items()]
        )
    except Exception:
        return UptimeResponse(services=[])


# ── POST /api/sentinel/subscribe (auth required) ──


@router.post("/api/sentinel/subscribe", response_model=SubscribeResponse)
async def subscribe(
    req: SubscribeRequest,
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
):
    sub_id = uuid.uuid4().hex[:16]
    now = datetime.now(UTC).isoformat()

    try:
        sub = Subscription(
            id=sub_id,
            url=req.url,
            events=req.events,
            active=True,
            created_at=now,
        )
        db.add(sub)
        await db.commit()
    except Exception:
        await persist(
            "subscriptions",
            {
                "id": sub_id,
                "url": req.url,
                "events": req.events,
                "active": True,
                "created_at": now,
            },
        )

    return SubscribeResponse(id=sub_id, message="Subscribed successfully")


# ── GET /api/sentinel/operations (auth required) ──


@router.get("/api/sentinel/operations", response_model=list[ActiveOperationResponse])
async def list_operations(
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
):
    try:
        result = await db.execute(
            select(ActiveOperation)
            .where(ActiveOperation.resolved_at.is_(None))
            .order_by(ActiveOperation.created_at.desc())
        )
        ops = result.scalars().all()
        return [
            ActiveOperationResponse(
                id=o.id,
                service=o.service,
                action=o.action,
                agent_id=o.agent_id,
                pid=o.pid,
                estimated_duration=o.estimated_duration,
                created_at=o.created_at,
                resolved_at=o.resolved_at,
                result=o.result,
            )
            for o in ops
        ]
    except Exception:
        return []


# ── GET /api/sentinel/events (no auth — SSE stream) ──


@router.get("/api/sentinel/events")
async def sse_events(request: Request):
    """SSE stream for real-time sentinel status updates."""
    import asyncio

    from sse import register_client, unregister_client

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    register_client(queue)

    async def generate():
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield msg
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unregister_client(queue)

    from starlette.responses import StreamingResponse

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Sysmon Proxy Routes (auth required) ──
# Proxy to system-monitor (port 9526) for service management + guardian


async def _proxy_get(path: str) -> JSONResponse:
    """Proxy a GET request to sysmon."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{SYSMON_BASE}/{path}")
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        log.warning("sysmon proxy error: %s %s", path, e)
        return JSONResponse(content={"error": str(e)}, status_code=502)


async def _proxy_post(path: str) -> JSONResponse:
    """Proxy a POST request to sysmon."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{SYSMON_BASE}/{path}")
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        log.warning("sysmon proxy error: %s %s", path, e)
        return JSONResponse(content={"error": str(e)}, status_code=502)


@router.get("/api/sentinel/sysmon/services")
async def proxy_services(_user: dict = Depends(require_auth)):
    return await _proxy_get("services")


@router.post("/api/sentinel/sysmon/services/{label:path}/enable")
async def proxy_svc_enable(label: str, _user: dict = Depends(require_auth)):
    return await _proxy_post(f"services/{label}/enable")


@router.post("/api/sentinel/sysmon/services/{label:path}/disable")
async def proxy_svc_disable(label: str, _user: dict = Depends(require_auth)):
    return await _proxy_post(f"services/{label}/disable")


@router.post("/api/sentinel/sysmon/services/{label:path}/restart")
async def proxy_svc_restart(label: str, _user: dict = Depends(require_auth)):
    return await _proxy_post(f"services/{label}/restart")


@router.get("/api/sentinel/sysmon/services/{label:path}/logs")
async def proxy_svc_logs(label: str, _user: dict = Depends(require_auth)):
    return await _proxy_get(f"services/{label}/logs")


@router.get("/api/sentinel/sysmon/guardian")
async def proxy_guardian(_user: dict = Depends(require_auth)):
    return await _proxy_get("guardian")


@router.post("/api/sentinel/sysmon/guardian/run")
async def proxy_guardian_run(_user: dict = Depends(require_auth)):
    return await _proxy_post("guardian/run")


# ── Store State ──


@router.get("/api/sentinel/store")
async def get_store_state(request: Request, _user: dict = Depends(require_auth)):
    """Return the current NgRx-style store state for Sentinel."""
    store = request.app.state.store
    return store.get_state()

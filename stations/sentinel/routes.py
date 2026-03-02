"""Sentinel API routes — 10 endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from auth import require_auth
from database import get_session, persist
from fastapi import APIRouter, Depends, Query
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
    except Exception:
        pass

    return ResolveResponse(message="Resolved (no matching operation found)")


# ── GET /api/sentinel/incidents (auth required) ──


@router.get("/api/sentinel/incidents", response_model=IncidentListResponse)
async def list_incidents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
    _user: dict = Depends(require_auth),
):
    try:
        # Count
        count_result = await db.execute(select(func.count()).select_from(Incident))
        total = count_result.scalar() or 0

        # Fetch
        result = await db.execute(
            select(Incident)
            .order_by(Incident.created_at.desc())
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

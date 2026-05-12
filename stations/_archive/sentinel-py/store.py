"""NgRx-style FeatureStore for Sentinel — intervention state machine.

Wraps the existing InterventionEngine/State FSM with a Redux-style
action/reducer/selector facade. Stations cannot import from core's
src.shared.* directly, so we add core/ to sys.path here.

State shape:
    {
        "services": {
            "<name>": {
                "status": str,      # healthy|observing|maintenance|intervening|repairing|escalated
                "light_status": str | None,
                "deep_status": str | None,
                "last_check": str | None,  # ISO timestamp
                "response_ms": float,
                "downtime_start": float,   # epoch, 0 = not down
            }
        },
        "interventions": {
            "<name>": {
                "state": str,           # INTERVENING|REPAIRING|ESCALATED
                "started_at": float,    # epoch
                "attempts": int,
                "repair_pane": str | None,
                "incident_id": str | None,
            }
        },
        "overall_health": str,          # healthy | degraded | critical
        "check_count": int,
    }
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# ── Path bootstrap — stations don't inherit core's Python path ──
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

import logging

from src.shared.actions import create_action, create_reducer, on
from src.shared.immutable_utils import to_immutable
from src.shared.middleware import LoggerMiddleware, PerformanceMiddleware
from src.shared.selectors import create_selector
from src.shared.store import FeatureStore, effect, register_effects

logger = logging.getLogger(__name__)

# ── Actions ──────────────────────────────────────────────────────────────────

HealthChecked = create_action("sentinel.health.checked")
# payload: {"service": str, "status": str, "response_ms": float, "check_type": str}

DeepChecked = create_action("sentinel.deep.checked")
# payload: {"service": str, "status": str}

InterventionStarted = create_action("sentinel.intervention.started")
# payload: {"service": str, "started_at": float}

InterventionCompleted = create_action("sentinel.intervention.completed")
# payload: {"service": str, "success": bool}

InterventionEscalated = create_action("sentinel.intervention.escalated")
# payload: {"service": str, "reason": str}

ServiceRecovered = create_action("sentinel.service.recovered")
# payload: {"service": str}

ServiceDown = create_action("sentinel.service.down")
# payload: {"service": str, "light_status": str, "response_ms": float}

RepairDispatched = create_action("sentinel.repair.dispatched")
# payload: {"service": str, "pane": str, "incident_id": str | None}

# ── Reducer helpers ───────────────────────────────────────────────────────────

_OVERALL_RANK = {"healthy": 0, "degraded": 1, "critical": 2}


def _compute_overall(services) -> str:
    """Derive overall_health from current service statuses."""
    statuses = [v.get("status", "healthy") for v in services.values()]
    critical_states = {"intervening", "repairing", "escalated"}
    degraded_states = {"observing", "maintenance"}
    if any(s in critical_states for s in statuses):
        return "critical"
    if any(s in degraded_states for s in statuses):
        return "degraded"
    return "healthy"


def _handle_health_checked(state, action) -> object:
    p = action.payload or {}
    service = p.get("service", "")
    status = p.get("status", "healthy")
    response_ms = p.get("response_ms", 0.0)
    now_iso = _fmt_time(time.time())

    # Map — use .get() from immutables
    current_map = state["services"]
    entry = current_map.get(service) if hasattr(current_map, "get") else {}
    if entry is None:
        entry = {}

    # Build updated entry dict
    updated_entry = (
        dict(entry)
        if isinstance(entry, dict)
        else ({k: v for k, v in entry.items()} if hasattr(entry, "items") else {})
    )
    updated_entry["light_status"] = status
    updated_entry["last_check"] = now_iso
    updated_entry["response_ms"] = response_ms

    # Derive FSM status — only HEALTHY / OBSERVING transition here
    current_fsm = updated_entry.get("status", "healthy")
    if status in ("unhealthy", "timeout"):
        if current_fsm == "healthy":
            updated_entry["status"] = "observing"
            updated_entry["downtime_start"] = time.time()
        # Leave other FSM states (MAINTENANCE, REPAIRING, etc.) as-is
    elif status in ("healthy", "skipped"):
        if current_fsm in ("healthy", "observing"):
            updated_entry["status"] = "healthy"
            updated_entry["downtime_start"] = 0.0

    new_services = state["services"].set(service, to_immutable(updated_entry))
    new_state = state.set("services", new_services)
    new_state = new_state.set("check_count", state["check_count"] + 1)
    new_state = new_state.set("overall_health", _compute_overall(new_services))
    return new_state


def _handle_deep_checked(state, action) -> object:
    p = action.payload or {}
    service = p.get("service", "")
    status = p.get("status", "healthy")

    services = state["services"]
    entry = services.get(service) if hasattr(services, "get") else {}
    if entry is None:
        entry = {}

    updated = dict(entry) if isinstance(entry, dict) else {k: v for k, v in entry.items()}
    updated["deep_status"] = status

    new_services = services.set(service, to_immutable(updated))
    new_state = state.set("services", new_services)
    new_state = new_state.set("overall_health", _compute_overall(new_services))
    return new_state


def _handle_service_down(state, action) -> object:
    p = action.payload or {}
    service = p.get("service", "")
    light_status = p.get("light_status", "unhealthy")
    response_ms = p.get("response_ms", 0.0)
    now = time.time()

    services = state["services"]
    entry = services.get(service) if hasattr(services, "get") else {}
    updated = (
        dict(entry)
        if isinstance(entry, dict)
        else ({k: v for k, v in entry.items()} if hasattr(entry, "items") else {})
    )
    updated["status"] = "observing"
    updated["light_status"] = light_status
    updated["response_ms"] = response_ms
    if not updated.get("downtime_start"):
        updated["downtime_start"] = now

    new_services = services.set(service, to_immutable(updated))
    new_state = state.set("services", new_services)
    new_state = new_state.set("overall_health", _compute_overall(new_services))
    return new_state


def _handle_intervention_started(state, action) -> object:
    p = action.payload or {}
    service = p.get("service", "")
    started_at = p.get("started_at", time.time())

    # Update services FSM status → intervening
    services = state["services"]
    svc_entry = services.get(service) if hasattr(services, "get") else {}
    svc_updated = (
        dict(svc_entry)
        if isinstance(svc_entry, dict)
        else ({k: v for k, v in svc_entry.items()} if hasattr(svc_entry, "items") else {})
    )
    svc_updated["status"] = "intervening"
    new_services = services.set(service, to_immutable(svc_updated))

    # Track in interventions
    interventions = state["interventions"]
    existing = interventions.get(service) if hasattr(interventions, "get") else {}
    if existing is None:
        existing = {}
    existing_dict = (
        dict(existing)
        if isinstance(existing, dict)
        else ({k: v for k, v in existing.items()} if hasattr(existing, "items") else {})
    )
    attempts = existing_dict.get("attempts", 0) + 1
    iv_entry = {
        "state": "INTERVENING",
        "started_at": started_at,
        "attempts": attempts,
        "repair_pane": existing_dict.get("repair_pane"),
        "incident_id": existing_dict.get("incident_id"),
    }
    new_interventions = interventions.set(service, to_immutable(iv_entry))

    new_state = state.set("services", new_services)
    new_state = new_state.set("interventions", new_interventions)
    new_state = new_state.set("overall_health", _compute_overall(new_services))
    return new_state


def _handle_repair_dispatched(state, action) -> object:
    p = action.payload or {}
    service = p.get("service", "")
    pane = p.get("pane", "")
    incident_id = p.get("incident_id")

    # Update services FSM status → repairing
    services = state["services"]
    svc_entry = services.get(service) if hasattr(services, "get") else {}
    svc_updated = (
        dict(svc_entry)
        if isinstance(svc_entry, dict)
        else ({k: v for k, v in svc_entry.items()} if hasattr(svc_entry, "items") else {})
    )
    svc_updated["status"] = "repairing"
    new_services = services.set(service, to_immutable(svc_updated))

    # Update intervention tracking
    interventions = state["interventions"]
    iv_entry = interventions.get(service) if hasattr(interventions, "get") else {}
    if iv_entry is None:
        iv_entry = {}
    iv_updated = (
        dict(iv_entry)
        if isinstance(iv_entry, dict)
        else ({k: v for k, v in iv_entry.items()} if hasattr(iv_entry, "items") else {})
    )
    iv_updated["state"] = "REPAIRING"
    iv_updated["repair_pane"] = pane
    if incident_id:
        iv_updated["incident_id"] = incident_id
    new_interventions = interventions.set(service, to_immutable(iv_updated))

    new_state = state.set("services", new_services)
    new_state = new_state.set("interventions", new_interventions)
    new_state = new_state.set("overall_health", _compute_overall(new_services))
    return new_state


def _handle_intervention_completed(state, action) -> object:
    p = action.payload or {}
    service = p.get("service", "")
    success = p.get("success", True)

    # Update services FSM status
    services = state["services"]
    svc_entry = services.get(service) if hasattr(services, "get") else {}
    svc_updated = (
        dict(svc_entry)
        if isinstance(svc_entry, dict)
        else ({k: v for k, v in svc_entry.items()} if hasattr(svc_entry, "items") else {})
    )
    svc_updated["status"] = "healthy" if success else "escalated"
    if success:
        svc_updated["downtime_start"] = 0.0
    new_services = services.set(service, to_immutable(svc_updated))

    # Clear intervention tracking
    interventions = state["interventions"]
    iv_entry = interventions.get(service) if hasattr(interventions, "get") else {}
    if iv_entry is not None:
        iv_updated = (
            dict(iv_entry)
            if isinstance(iv_entry, dict)
            else ({k: v for k, v in iv_entry.items()} if hasattr(iv_entry, "items") else {})
        )
        iv_updated["state"] = "COMPLETED" if success else "FAILED"
        iv_updated["repair_pane"] = None
        new_interventions = interventions.set(service, to_immutable(iv_updated))
    else:
        new_interventions = interventions

    new_state = state.set("services", new_services)
    new_state = new_state.set("interventions", new_interventions)
    new_state = new_state.set("overall_health", _compute_overall(new_services))
    return new_state


def _handle_intervention_escalated(state, action) -> object:
    p = action.payload or {}
    service = p.get("service", "")
    reason = p.get("reason", "")

    # Update services FSM status → escalated
    services = state["services"]
    svc_entry = services.get(service) if hasattr(services, "get") else {}
    svc_updated = (
        dict(svc_entry)
        if isinstance(svc_entry, dict)
        else ({k: v for k, v in svc_entry.items()} if hasattr(svc_entry, "items") else {})
    )
    svc_updated["status"] = "escalated"
    new_services = services.set(service, to_immutable(svc_updated))

    # Update intervention tracking
    interventions = state["interventions"]
    iv_entry = interventions.get(service) if hasattr(interventions, "get") else {}
    if iv_entry is not None:
        iv_updated = (
            dict(iv_entry)
            if isinstance(iv_entry, dict)
            else ({k: v for k, v in iv_entry.items()} if hasattr(iv_entry, "items") else {})
        )
        iv_updated["state"] = "ESCALATED"
        iv_updated["reason"] = reason
        new_interventions = interventions.set(service, to_immutable(iv_updated))
    else:
        new_interventions = interventions

    new_state = state.set("services", new_services)
    new_state = new_state.set("interventions", new_interventions)
    new_state = new_state.set("overall_health", _compute_overall(new_services))
    return new_state


def _handle_service_recovered(state, action) -> object:
    p = action.payload or {}
    service = p.get("service", "")

    services = state["services"]
    svc_entry = services.get(service) if hasattr(services, "get") else {}
    if svc_entry is None:
        return state
    svc_updated = (
        dict(svc_entry)
        if isinstance(svc_entry, dict)
        else ({k: v for k, v in svc_entry.items()} if hasattr(svc_entry, "items") else {})
    )
    svc_updated["status"] = "healthy"
    svc_updated["downtime_start"] = 0.0
    new_services = services.set(service, to_immutable(svc_updated))

    # Remove intervention tracking for recovered service
    interventions = state["interventions"]
    if hasattr(interventions, "get") and interventions.get(service) is not None:
        # Keep the record but mark as resolved
        iv_entry = interventions.get(service)
        iv_updated = (
            dict(iv_entry)
            if isinstance(iv_entry, dict)
            else ({k: v for k, v in iv_entry.items()} if hasattr(iv_entry, "items") else {})
        )
        iv_updated["state"] = "RESOLVED"
        new_interventions = interventions.set(service, to_immutable(iv_updated))
    else:
        new_interventions = interventions

    new_state = state.set("services", new_services)
    new_state = new_state.set("interventions", new_interventions)
    new_state = new_state.set("overall_health", _compute_overall(new_services))
    return new_state


# ── Reducer ───────────────────────────────────────────────────────────────────

sentinel_reducer = create_reducer(
    {
        "services": {},  # service_name → {status, light_status, deep_status, ...}
        "interventions": {},  # service_name → {state, started_at, attempts, repair_pane}
        "overall_health": "healthy",
        "check_count": 0,
    },
    on(HealthChecked, _handle_health_checked),
    on(DeepChecked, _handle_deep_checked),
    on(ServiceDown, _handle_service_down),
    on(InterventionStarted, _handle_intervention_started),
    on(RepairDispatched, _handle_repair_dispatched),
    on(InterventionCompleted, _handle_intervention_completed),
    on(InterventionEscalated, _handle_intervention_escalated),
    on(ServiceRecovered, _handle_service_recovered),
)

# ── Selectors ─────────────────────────────────────────────────────────────────

select_services = create_selector(lambda s: s["services"])

select_down_services = create_selector(
    lambda s: s["services"],
    result_fn=lambda svcs: {
        k: v
        for k, v in (svcs.items() if hasattr(svcs, "items") else {}.items())
        if (v.get("status") if isinstance(v, dict) else v["status"])
        in ("observing", "intervening", "repairing", "escalated")
    },
)

select_active_interventions = create_selector(
    lambda s: s["interventions"],
    result_fn=lambda ivs: {
        k: v
        for k, v in (ivs.items() if hasattr(ivs, "items") else {}.items())
        if (v.get("state") if isinstance(v, dict) else v["state"]) in ("INTERVENING", "REPAIRING")
    },
)

select_overall_health = create_selector(lambda s: s["overall_health"])

select_check_count = create_selector(lambda s: s["check_count"])

select_services_by_group = create_selector(
    lambda s: s["services"],
    result_fn=lambda svcs: _group_services(svcs),
)


def _group_services(svcs) -> dict:
    """Group services by their group field."""
    groups: dict = {}
    items = svcs.items() if hasattr(svcs, "items") else {}
    for name, v in items:
        group = (v.get("group") if isinstance(v, dict) else v.get("group", "")) or "unknown"
        groups.setdefault(group, {})[name] = v
    return groups


select_escalated_services = create_selector(
    lambda s: s["services"],
    result_fn=lambda svcs: {
        k: v
        for k, v in (svcs.items() if hasattr(svcs, "items") else {}.items())
        if (v.get("status") if isinstance(v, dict) else v["status"]) == "escalated"
    },
)

# ── Store instance ────────────────────────────────────────────────────────────

sentinel_store = FeatureStore(
    "sentinel",
    sentinel_reducer,
    middlewares=[
        LoggerMiddleware("sentinel"),
        PerformanceMiddleware(),
    ],
)

# ── Effects ───────────────────────────────────────────────────────────────────


@effect(ServiceDown, store=sentinel_store)
async def log_service_down_alert(action, store) -> None:
    """Log alert when a service goes down for on-call visibility."""
    p = action.payload or {}
    service = p.get("service", "unknown")
    light_status = p.get("light_status", "unhealthy")
    response_ms = p.get("response_ms", 0.0)
    logger.warning(
        "sentinel.service_down",
        extra={
            "service": service,
            "light_status": light_status,
            "response_ms": response_ms,
        },
    )


@effect(InterventionEscalated, store=sentinel_store)
async def log_escalation_warning(action, store) -> None:
    """Log WARNING when manual intervention is required."""
    p = action.payload or {}
    service = p.get("service", "unknown")
    reason = p.get("reason", "")

    # Extract intervention info (attempt count)
    state = store.get_state()
    iv_entry = state.get("interventions", {}).get(service, {})
    attempts = iv_entry.get("attempts", 0) if isinstance(iv_entry, dict) else 0

    logger.warning(
        "sentinel.intervention_escalated — manual intervention required",
        extra={
            "service": service,
            "reason": reason,
            "attempts": attempts,
        },
    )


@effect(ServiceRecovered, store=sentinel_store)
async def log_recovery_with_duration(action, store) -> None:
    """Log recovery and calculate downtime duration in seconds."""
    p = action.payload or {}
    service = p.get("service", "unknown")

    # Use downtime_start from payload since reducer already cleared it in state
    downtime_start = p.get("downtime_start", 0.0)
    if downtime_start:
        duration_s = round(time.time() - downtime_start, 1)
        logger.info(
            "sentinel.service_recovered",
            extra={
                "service": service,
                "downtime_seconds": duration_s,
            },
        )
    else:
        logger.info(
            "sentinel.service_recovered",
            extra={"service": service},
        )


register_effects(
    sentinel_store,
    log_service_down_alert,
    log_escalation_warning,
    log_recovery_with_duration,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _fmt_time(ts: float) -> str | None:
    if not ts:
        return None
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, tz=UTC).isoformat()

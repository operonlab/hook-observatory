"""Intervention state machine: 5-minute rule with agent awareness.

States:
    HEALTHY → OBSERVING → INTERVENING → REPAIRING → ESCALATED
                ↓                                      ↑
            [agent notified] → MAINTENANCE            [timeout/fail]
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from config import config

logger = logging.getLogger(__name__)


class State(str, Enum):
    HEALTHY = "healthy"
    OBSERVING = "observing"
    MAINTENANCE = "maintenance"
    INTERVENING = "intervening"
    REPAIRING = "repairing"
    ESCALATED = "escalated"


@dataclass
class ServiceTracker:
    """Track per-service health state."""

    service: str
    state: State = State.HEALTHY
    light_status: str | None = None
    deep_status: str | None = None
    last_light_check: float = 0.0
    last_deep_check: float = 0.0
    first_failure_at: float = 0.0
    agent_id: str | None = None
    agent_notified_at: float = 0.0
    agent_pid: int | None = None
    repair_pane: str | None = None
    repair_started_at: float = 0.0
    incident_id: str | None = None
    response_ms: float = 0.0
    last_notified_at: float = 0.0


@dataclass
class InterventionEngine:
    """Manages the 5-minute intervention FSM for all services."""

    trackers: dict[str, ServiceTracker] = field(default_factory=dict)
    lock_dir: Path = field(default_factory=lambda: config.lock_dir)

    def __post_init__(self):
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    def get_tracker(self, service: str) -> ServiceTracker:
        if service not in self.trackers:
            self.trackers[service] = ServiceTracker(service=service)
        return self.trackers[service]

    def update_light(self, service: str, status: str, response_ms: float = 0.0) -> None:
        """Update light check result and transition state."""
        t = self.get_tracker(service)
        t.light_status = status
        t.last_light_check = time.time()
        t.response_ms = response_ms
        self._evaluate(t)

    def update_deep(self, service: str, status: str) -> None:
        """Update deep check result and transition state."""
        t = self.get_tracker(service)
        t.deep_status = status
        t.last_deep_check = time.time()
        self._evaluate(t)

    def notify_agent(
        self, service: str, agent_id: str, pid: int | None = None, estimated_duration: int = 300
    ) -> None:
        """Agent notifies it's working on a service."""
        t = self.get_tracker(service)
        t.agent_id = agent_id
        t.agent_pid = pid
        t.agent_notified_at = time.time()
        if t.state in (State.HEALTHY, State.OBSERVING):
            t.state = State.MAINTENANCE
            logger.info("Service %s → MAINTENANCE (agent: %s)", service, agent_id)

        # Write lock file
        self._write_lock(service, agent_id, estimated_duration)

    def resolve_agent(self, service: str, agent_id: str) -> None:
        """Agent reports completion."""
        t = self.get_tracker(service)
        if t.agent_id == agent_id:
            t.agent_id = None
            t.agent_pid = None
            t.agent_notified_at = 0.0
            # Don't go to HEALTHY yet — next check will determine
            if t.state == State.MAINTENANCE:
                t.state = State.HEALTHY
                t.first_failure_at = 0.0
                logger.info("Service %s → HEALTHY (agent resolved)", service)

        self._remove_lock(service)

    def set_repairing(self, service: str, pane: str) -> None:
        """Mark service as being repaired by sentinel."""
        t = self.get_tracker(service)
        t.state = State.REPAIRING
        t.repair_pane = pane
        t.repair_started_at = time.time()
        logger.info("Service %s → REPAIRING (pane: %s)", service, pane)

    def set_repair_done(self, service: str, success: bool) -> None:
        """Repair completed."""
        t = self.get_tracker(service)
        t.repair_pane = None
        if success:
            t.state = State.HEALTHY
            t.first_failure_at = 0.0
            logger.info("Service %s → HEALTHY (repair success)", service)
        else:
            t.state = State.ESCALATED
            logger.warning("Service %s → ESCALATED (repair failed)", service)

    def should_intervene(self, service: str) -> bool:
        """Check if sentinel should dispatch auto-repair."""
        t = self.get_tracker(service)
        return t.state == State.INTERVENING

    def sweep_expired_locks(self) -> None:
        """Periodically clean up expired locks for services not in check lists.

        Called from the main loop alongside light checks to ensure virtual
        services (workshop-services, frontend-build, etc.) transition back
        from MAINTENANCE once their lock expires.

        Also clears stale agent_id when lock has expired and agent PID
        is no longer alive (or was never set — e.g. hook-originated notify).
        """
        for t in list(self.trackers.values()):
            if t.state == State.MAINTENANCE:
                if not self._has_active_lock(t.service):
                    # Lock expired — check if agent is still alive
                    if t.agent_pid and _pid_alive(t.agent_pid):
                        continue  # Agent still running, don't clear
                    t.agent_id = None
                    t.agent_pid = None
                    t.state = State.HEALTHY
                    t.first_failure_at = 0.0
                    logger.info("Service %s → HEALTHY (lock expired, sweep)", t.service)

    def get_all_statuses(self) -> dict[str, dict]:
        """Get all service statuses for API response."""
        from checker import GROUP_MAP, merge_status

        result = {}
        for name, t in self.trackers.items():
            overall = merge_status(t.light_status, t.deep_status)
            if t.state == State.MAINTENANCE:
                overall = "maintenance"
            result[name] = {
                "service": name,
                "status": overall,
                "group": GROUP_MAP.get(name),
                "state": t.state.value,
                "light_status": t.light_status,
                "deep_status": t.deep_status,
                "last_check": _fmt_time(t.last_light_check),
                "response_ms": t.response_ms,
            }
        return result

    # ── Internal ──

    def _evaluate(self, t: ServiceTracker) -> None:
        """Evaluate state transition based on current check results."""
        from checker import merge_status

        overall = merge_status(t.light_status, t.deep_status)
        now = time.time()

        # Maintenance takes priority — agent is working
        if t.state == State.MAINTENANCE:
            if self._has_active_lock(t.service) or t.agent_id:
                # Check if agent PID is still alive
                if t.agent_pid and not _pid_alive(t.agent_pid):
                    ttl = now - t.agent_notified_at
                    if ttl > config.check.intervention_delay:
                        t.state = State.INTERVENING
                        logger.warning("Service %s → INTERVENING (agent PID dead)", t.service)
                return
            # Lock gone + no agent → re-evaluate
            t.state = State.HEALTHY
            t.agent_id = None

        if t.state == State.REPAIRING:
            if now - t.repair_started_at > config.check.repair_timeout:
                t.state = State.ESCALATED
                logger.warning("Service %s → ESCALATED (repair timeout)", t.service)
            return

        if t.state == State.ESCALATED:
            # Only recover from escalated if healthy again
            if overall == "operational":
                t.state = State.HEALTHY
                t.first_failure_at = 0.0
                logger.info("Service %s → HEALTHY (recovered from escalated)", t.service)
            return

        # Normal transitions
        if overall == "operational":
            if t.state != State.HEALTHY:
                logger.info("Service %s → HEALTHY", t.service)
            t.state = State.HEALTHY
            t.first_failure_at = 0.0
        elif overall in ("degraded", "major_outage", "partial_outage"):
            if t.state == State.HEALTHY:
                t.state = State.OBSERVING
                t.first_failure_at = now
                logger.warning("Service %s → OBSERVING (%s)", t.service, overall)
            elif t.state == State.OBSERVING:
                elapsed = now - t.first_failure_at
                if elapsed >= config.check.intervention_delay:
                    t.state = State.INTERVENING
                    logger.warning("Service %s → INTERVENING (%.0fs elapsed)", t.service, elapsed)

    def _write_lock(self, service: str, agent_id: str, estimated_duration: int) -> None:
        try:
            lock_file = self.lock_dir / f"{service}.lock"
            lock_file.write_text(f"{agent_id}\n{estimated_duration}\n{time.time()}")
        except OSError:
            logger.warning("Failed to write lock for %s", service)

    def _remove_lock(self, service: str) -> None:
        try:
            lock_file = self.lock_dir / f"{service}.lock"
            lock_file.unlink(missing_ok=True)
        except OSError:
            pass

    def _has_active_lock(self, service: str) -> bool:
        """Check if lock file exists and is not expired."""
        lock_file = self.lock_dir / f"{service}.lock"
        if not lock_file.exists():
            return False
        try:
            parts = lock_file.read_text().strip().split("\n")
            if len(parts) >= 3:
                est_dur = int(parts[1])
                created = float(parts[2])
                # Lock TTL = estimated_duration + 5 min grace
                if time.time() - created > est_dur + 300:
                    lock_file.unlink(missing_ok=True)
                    return False
            return True
        except (ValueError, OSError):
            return False


def _pid_alive(pid: int) -> bool:
    """Check if a PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _fmt_time(ts: float) -> str | None:
    if ts == 0:
        return None
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, tz=UTC).isoformat()

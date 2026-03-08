"""Auto-remediation: simple restart first, AI repair as fallback."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from prompt_templates import build_repair_prompt

logger = logging.getLogger(__name__)

RELAY_SCRIPT = Path.home() / ".claude/skills/tmux-relay/scripts/relay.sh"
PANE_POOL_SCRIPT = Path.home() / ".claude/skills/tmux-relay/scripts/pane_pool.sh"
SIGNAL_DIR = Path("/tmp")

WORKSHOP_SERVICES = Path.home() / "workshop/scripts/workshop_services.py"
PYTHON = Path.home() / ".local/bin/python3"

# Map sentinel service names → workshop_services.py service names
# Only services managed by workshop_services.py are eligible for simple restart
SIMPLE_RESTART_MAP: dict[str, str] = {
    "core": "core",
    "hook-observatory": "hook-observatory",
    "system-monitor": "system-monitor",
    "agent-metrics": "agent-metrics",
    "agent-vista": "agent-vista",
    "litellm": "litellm",
    "auto-survey": "auto-survey",
    "capture-console": "capture-console",
}

# Docker-managed services: restart via docker
DOCKER_RESTART_MAP: dict[str, str] = {
    "postgres": "ws-infra-postgres-1",
    "redis": "ws-infra-redis-1",
    "rustfs": "ws-infra-rustfs-1",
    "bark": "bark-server",
    "ntfy": "ws-infra-ntfy-1",
}


class SimpleRestarter:
    """Fast, direct service restart without AI involvement."""

    async def try_restart(self, service: str) -> bool:
        """Attempt a simple restart. Returns True if the restart command succeeded."""
        if service in SIMPLE_RESTART_MAP:
            return await self._restart_workshop_service(SIMPLE_RESTART_MAP[service])
        if service in DOCKER_RESTART_MAP:
            return await self._restart_docker(DOCKER_RESTART_MAP[service])
        return False

    @staticmethod
    def can_restart(service: str) -> bool:
        return service in SIMPLE_RESTART_MAP or service in DOCKER_RESTART_MAP

    async def _restart_workshop_service(self, name: str) -> bool:
        if not WORKSHOP_SERVICES.exists():
            logger.warning("workshop_services.py not found")
            return False
        try:
            # Stop first (kill old process + clean PID), then start
            for action in ("stop", "start"):
                proc = await asyncio.create_subprocess_exec(
                    str(PYTHON),
                    str(WORKSHOP_SERVICES),
                    action,
                    name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=45)
            logger.info("Simple restart succeeded for %s", name)
            return True
        except (TimeoutError, FileNotFoundError, OSError) as e:
            logger.error("Simple restart failed for %s: %s", name, e)
            return False

    async def _restart_docker(self, container: str) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "restart",
                container,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode == 0:
                logger.info("Docker restart succeeded for %s", container)
                return True
            logger.error("Docker restart failed for %s: %s", container, stderr.decode()[:200])
            return False
        except (TimeoutError, FileNotFoundError) as e:
            logger.error("Docker restart failed for %s: %s", container, e)
            return False


@dataclass
class RepairJob:
    service: str
    pane: str
    signal_file: Path
    started_at: float
    timeout: float


class Remediator:
    """Dispatches repair agents and tracks their completion."""

    def __init__(self):
        self._active_jobs: dict[str, RepairJob] = {}

    async def dispatch(self, service: str, detail: str, timeout: float = 600.0) -> str | None:
        """Dispatch a repair agent. Returns pane ID or None on failure."""
        if service in self._active_jobs:
            logger.warning("Repair already active for %s", service)
            return self._active_jobs[service].pane

        # Acquire a relay pane
        pane = await self._acquire_pane()
        if not pane:
            logger.error("No relay pane available for repair of %s", service)
            return None

        # Build prompt
        prompt = build_repair_prompt(service, detail)
        signal_file = SIGNAL_DIR / f"sentinel-repair-{service}-{int(time.time())}"

        # Dispatch via relay
        command = f'claude -p "{prompt}"'
        success = await self._relay_dispatch(pane, command, signal_file)

        if success:
            self._active_jobs[service] = RepairJob(
                service=service,
                pane=pane,
                signal_file=signal_file,
                started_at=time.time(),
                timeout=timeout,
            )
            logger.info("Repair dispatched for %s on pane %s", service, pane)
            return pane
        else:
            logger.error("Failed to dispatch repair for %s", service)
            return None

    async def check_completion(self, service: str) -> str | None:
        """Check if a repair job is done. Returns 'success' / 'timeout' / 'running' / None."""
        job = self._active_jobs.get(service)
        if not job:
            return None

        # Check signal file
        if job.signal_file.exists():
            try:
                result = job.signal_file.read_text().strip()
                job.signal_file.unlink(missing_ok=True)
            except OSError:
                result = "unknown"
            del self._active_jobs[service]
            logger.info("Repair completed for %s: %s", service, result)
            return "success" if "error" not in result.lower() else "failure"

        # Check timeout
        if time.time() - job.started_at > job.timeout:
            del self._active_jobs[service]
            logger.warning("Repair timed out for %s", service)
            return "timeout"

        return "running"

    @property
    def active_repairs(self) -> dict[str, RepairJob]:
        return dict(self._active_jobs)

    async def _acquire_pane(self) -> str | None:
        """Acquire a pane from the pool."""
        if not PANE_POOL_SCRIPT.exists():
            logger.warning("pane_pool.sh not found at %s", PANE_POOL_SCRIPT)
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                str(PANE_POOL_SCRIPT),
                "acquire",
                "1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode == 0:
                pane = stdout.decode().strip()
                return pane if pane else None
        except (TimeoutError, FileNotFoundError):
            pass
        return None

    async def _relay_dispatch(self, pane: str, command: str, signal_file: Path) -> bool:
        """Dispatch command via relay.sh."""
        if not RELAY_SCRIPT.exists():
            logger.warning("relay.sh not found at %s", RELAY_SCRIPT)
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                str(RELAY_SCRIPT),
                pane,
                "",
                command,
                "--no-forward",
                "--signal",
                str(signal_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            return proc.returncode == 0
        except (TimeoutError, FileNotFoundError):
            return False

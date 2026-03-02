"""Auto-remediation via tmux-relay: dispatch claude -p repair agents."""

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

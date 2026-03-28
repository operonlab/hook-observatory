"""Auto-remediation: simple restart → frontend rebuild → AI repair.

Three layers:
  Layer 1: SimpleRestarter — process/docker restart (fastest, no code changes)
  Layer 2: FrontendRebuilder — pnpm build + nginx reload (for stale builds)
  Layer 3: Remediator — AI agent via claude -p (code-level diagnosis & fix)
"""

from __future__ import annotations

import asyncio
import logging
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

from prompt_templates import build_repair_prompt

logger = logging.getLogger(__name__)

# ── Remediation timeout presets (seconds) ──

_TIMEOUT_SERVICE_RESTART = 45  # workshop_services.py stop/start cycle
_TIMEOUT_PORT_CHECK = 10  # process status / port availability check
_TIMEOUT_DOCKER_RESTART = 30  # docker restart container
_TIMEOUT_INFRA_RESTART = 60  # infrastructure engine restart (e.g. OrbStack)
_TIMEOUT_BUILD = 120  # frontend pnpm build
_TIMEOUT_NGINX_RELOAD = 10  # nginx -s reload
_TIMEOUT_GIT_OP = 15  # git / relay dispatch operations
_SLEEP_POST_KILL = 2  # settle after process kill / stop
_SLEEP_POST_RESTART = 5  # settle after service restart
_SLEEP_ENGINE_STARTUP = 15  # wait for infra engine (OrbStack) to fully start

RELAY_SCRIPT = Path.home() / ".claude/skills/tmux-relay/scripts/relay.sh"
PANE_POOL_SCRIPT = Path.home() / ".claude/skills/tmux-relay/scripts/pane_pool.sh"
SIGNAL_DIR = Path("/tmp")  # noqa: S108

WORKSHOP_SERVICES = Path.home() / "workshop/scripts/workshop_services.py"
PYTHON = Path.home() / ".local/bin/python3"
WORKBENCH_DIR = Path.home() / "workshop/workbench"
PNPM = "/opt/homebrew/opt/node@22/lib/node_modules/corepack/shims/pnpm"


# ── Shared async subprocess runner ──


async def _run_cmd(
    cmd: list[str],
    *,
    timeout: float = 30.0,  # noqa: ASYNC109
    label: str = "",
    check: bool = True,
    cwd: str | None = None,
) -> tuple[int, str, str]:
    """Run async subprocess with timeout and logging.

    Returns (returncode, stdout, stderr).
    Raises TimeoutError if timeout exceeded.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **({"cwd": cwd} if cwd else {}),
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except TimeoutError:
        proc.kill()
        raise
    stdout = stdout_bytes.decode().strip() if stdout_bytes else ""
    stderr = stderr_bytes.decode().strip() if stderr_bytes else ""
    if check and proc.returncode != 0:
        logger.warning(
            "%s failed (rc=%d): %s",
            label or " ".join(cmd[:2]),
            proc.returncode,
            stderr[:200],
        )
    return proc.returncode, stdout, stderr


# Map sentinel service names → workshop_services.py service names
# Only services managed by workshop_services.py are eligible for simple restart
SIMPLE_RESTART_MAP: dict[str, str] = {
    "core": "core",
    "paper": "paper",
    "intelflow": "intelflow",
    "invest": "invest",
    "hook-observatory": "hook-observatory",
    "session-channel": "session-channel",
    "system-monitor": "system-monitor",
    "agent-metrics": "agent-metrics",
    "agent-vista": "agent-vista",
    "litellm": "litellm",
    "auto-survey": "auto-survey",
    "capture-console": "capture-console",
    "anvil": "anvil",
    "blog": "blog",
    "cronicle": "cronicle",
    "mcpproxy": "mcpproxy",
    "tmux-webui": "tmux-webui",
    "fleet": "fleet",
    "stt": "stt",
    "ocr": "ocr",
    "voice-gateway": "voice-gateway",
    "translate": "translate",
}

# Docker-managed services: restart via docker
DOCKER_RESTART_MAP: dict[str, str] = {
    "postgres": "ws-infra-postgres-1",
    "redis": "ws-infra-redis-1",
    "rustfs": "ws-infra-rustfs-1",
    "bark": "ws-infra-bark-1",
    "qdrant": "ws-infra-qdrant-1",
}

# Infrastructure engine restarts: sentinel name → command args
INFRA_RESTART_MAP: dict[str, list[str]] = {
    "orbstack": ["orbctl", "start"],
}


class SimpleRestarter:
    """Fast, direct service restart without AI involvement."""

    async def try_restart(self, service: str) -> bool:
        """Attempt a simple restart. Returns True if the restart command succeeded."""
        if service in SIMPLE_RESTART_MAP:
            return await self._restart_workshop_service(SIMPLE_RESTART_MAP[service])
        if service in DOCKER_RESTART_MAP:
            return await self._restart_docker(DOCKER_RESTART_MAP[service])
        if service in INFRA_RESTART_MAP:
            return await self._restart_infra(service)
        return False

    @staticmethod
    def can_restart(service: str) -> bool:
        return (
            service in SIMPLE_RESTART_MAP
            or service in DOCKER_RESTART_MAP
            or service in INFRA_RESTART_MAP
        )

    async def _restart_workshop_service(self, name: str) -> bool:
        if not WORKSHOP_SERVICES.exists():
            logger.warning("workshop_services.py not found")
            return False
        try:
            # Stop first (kill old process + clean PID), then start
            for action in ("stop", "start"):
                await _run_cmd(
                    [str(PYTHON), str(WORKSHOP_SERVICES), action, name],
                    timeout=_TIMEOUT_SERVICE_RESTART,
                    label=f"workshop_services {action} {name}",
                    check=False,
                )
            # Brief wait then verify the process came back
            await asyncio.sleep(_SLEEP_POST_KILL)
            rc, _, _ = await _run_cmd(
                [str(PYTHON), str(WORKSHOP_SERVICES), "status", name],
                timeout=_TIMEOUT_PORT_CHECK,
                label=f"workshop_services status {name}",
                check=False,
            )
            if rc != 0:
                logger.warning("Service %s restarted but health check failed", name)
                return False
            logger.info("Simple restart succeeded for %s", name)
            return True
        except (TimeoutError, FileNotFoundError, OSError) as e:
            logger.error("Simple restart failed for %s: %s", name, e)
            return False

    async def _restart_docker(self, container: str) -> bool:
        try:
            rc, _, stderr = await _run_cmd(
                ["docker", "restart", container],
                timeout=_TIMEOUT_DOCKER_RESTART,
                label=f"docker restart {container}",
                check=False,
            )
            if rc == 0:
                logger.info("Docker restart succeeded for %s", container)
                return True
            logger.error("Docker restart failed for %s: %s", container, stderr[:200])
            return False
        except (TimeoutError, FileNotFoundError) as e:
            logger.error("Docker restart failed for %s: %s", container, e)
            return False

    async def _restart_infra(self, service: str) -> bool:
        """Restart infrastructure engines (e.g. OrbStack Docker engine)."""
        cmd = INFRA_RESTART_MAP.get(service)
        if not cmd:
            return False
        try:
            rc, _, stderr = await _run_cmd(
                cmd,
                timeout=_TIMEOUT_INFRA_RESTART,
                label=f"infra restart {service}",
                check=False,
            )
            if rc == 0:
                logger.info("Infra restart succeeded for %s", service)
                # Wait for engine to be fully ready
                await asyncio.sleep(_SLEEP_POST_RESTART)
                return True
            # Fallback: if orbctl fails, try opening the app
            if service == "orbstack":
                logger.warning("orbctl start failed, trying open -a OrbStack")
                await _run_cmd(
                    ["open", "-a", "OrbStack"],
                    timeout=_TIMEOUT_PORT_CHECK,
                    label="open OrbStack",
                    check=False,
                )
                await asyncio.sleep(_SLEEP_ENGINE_STARTUP)  # Wait for app + engine startup
                retry_rc, _, _ = await _run_cmd(
                    cmd,
                    timeout=_TIMEOUT_DOCKER_RESTART,
                    label=f"infra restart {service} (retry)",
                    check=False,
                )
                if retry_rc == 0:
                    logger.info("Infra restart succeeded for %s (fallback)", service)
                    await asyncio.sleep(_SLEEP_POST_RESTART)
                    return True
            logger.error("Infra restart failed for %s: %s", service, stderr[:200])
            return False
        except (TimeoutError, FileNotFoundError) as e:
            logger.error("Infra restart failed for %s: %s", service, e)
            return False


class FrontendRebuilder:
    """Layer 2: Rebuild frontend and reload Nginx.

    Handles frontend-* service failures that SimpleRestarter can't fix.
    A rebuild regenerates chunk hashes + SW version, clearing stale caches.
    """

    @staticmethod
    def can_rebuild(service: str) -> bool:
        """Check if this service is a frontend module eligible for rebuild."""
        return service.startswith("frontend") and service != "frontend"

    async def try_rebuild(self) -> bool:
        """Run pnpm build in workbench/ and reload Nginx. Returns True on success."""
        if not WORKBENCH_DIR.exists():
            logger.warning("workbench/ not found at %s", WORKBENCH_DIR)
            return False

        try:
            # Step 1: pnpm build
            logger.info("Frontend rebuild: running pnpm build...")
            rc, _, stderr = await _run_cmd(
                [PNPM, "run", "build"],
                timeout=_TIMEOUT_BUILD,
                label="pnpm build",
                check=False,
                cwd=str(WORKBENCH_DIR),
            )
            if rc != 0:
                logger.error("Frontend rebuild failed: %s", stderr[-500:])
                return False

            logger.info("Frontend rebuild succeeded")

            # Step 2: Nginx reload
            await _run_cmd(
                ["nginx", "-s", "reload"],
                timeout=_TIMEOUT_NGINX_RELOAD,
                label="nginx reload",
                check=False,
            )
            return True

        except TimeoutError:
            logger.error("Frontend rebuild timed out")
            return False
        except FileNotFoundError as e:
            logger.error("Frontend rebuild tool not found: %s", e)
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

    async def dispatch(
        self,
        service: str,
        detail: str,
        timeout: float = 600.0,  # noqa: ASYNC109
        url: str = "",
    ) -> str | None:
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
        prompt = build_repair_prompt(service, detail, url=url)
        signal_file = SIGNAL_DIR / f"sentinel-repair-{service}-{int(time.time())}"

        # Dispatch via relay — shlex.quote prevents quote injection in the prompt
        command = f"claude -p {shlex.quote(prompt)}"
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
            rc, stdout, _ = await _run_cmd(
                ["bash", str(PANE_POOL_SCRIPT), "acquire", "1"],
                timeout=_TIMEOUT_PORT_CHECK,
                label="pane_pool acquire",
                check=False,
            )
            if rc == 0:
                return stdout if stdout else None
        except (TimeoutError, FileNotFoundError):
            pass
        return None

    async def _relay_dispatch(self, pane: str, command: str, signal_file: Path) -> bool:
        """Dispatch command via relay.sh."""
        if not RELAY_SCRIPT.exists():
            logger.warning("relay.sh not found at %s", RELAY_SCRIPT)
            return False

        try:
            rc, _, _ = await _run_cmd(
                [
                    "bash", str(RELAY_SCRIPT), pane, "",
                    command, "--no-forward", "--signal", str(signal_file),
                ],
                timeout=_TIMEOUT_GIT_OP,
                label="relay dispatch",
                check=False,
            )
            return rc == 0
        except (TimeoutError, FileNotFoundError):
            return False

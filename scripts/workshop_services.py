#!/usr/bin/env python3
"""
Workshop Unified Service Launcher
Single entry point for all workshop daemon services.
"""

import gzip
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

# Port registry — single source of truth
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "libs" / "python" / "src"))
from sdk_client.port_registry import get, get_port

# ── Daemon PATH (launchd does not inherit .zshenv) ─────────────
_DAEMON_PATH = (
    "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin"
    ":/usr/bin:/bin:/usr/sbin:/sbin:/Users/joneshong/.local/bin"
)
_DAEMON_ENV = {**dict(os.environ), "PATH": _DAEMON_PATH}

# ── Configuration ──────────────────────────────────────────────
LOG_BASE = Path("/opt/homebrew/var/log/workshop")
PID_DIR = Path("/opt/homebrew/var/run/workshop")
LOG_RETAIN_DAYS = 90
LOG_MAX_SIZE = 10 * 1024 * 1024  # 10MB


def _litellm_preflight() -> tuple[bool, str]:
    """Verify litellm[proxy] extras are intact in its uv tool env.

    `uv tool upgrade litellm` does not re-resolve extras, so the
    `[proxy]`-only deps (backoff, prisma, etc.) can silently disappear.
    Catch it here with a clear remediation hint instead of letting the
    proxy crash with ImportError after binding port 4000.
    """
    py = "/Users/joneshong/.local/share/uv/tools/litellm/bin/python"
    try:
        # `backoff` is the canary: litellm/proxy/proxy_server.py imports it
        # unconditionally and raises ImportError at startup if missing.
        # Other [proxy] extras (prisma, etc.) are config-conditional, so we
        # don't preflight them — they'll surface in stderr log if needed.
        result = subprocess.run(
            [py, "-c", "import backoff"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, ""
        missing = result.stderr.strip().splitlines()[-1] if result.stderr else "unknown"
        return False, (
            f"litellm[proxy] extras missing ({missing}). "
            "Fix: uv tool install --force 'litellm[proxy]'  "
            "(NOT 'uv tool upgrade litellm' — that drops extras)"
        )
    except FileNotFoundError:
        return False, (
            f"litellm uv tool env not found at {py}. Fix: uv tool install 'litellm[proxy]'"
        )
    except subprocess.TimeoutExpired:
        return False, f"litellm preflight timed out (10s) — check {py}"


# Service registry: list of dicts with name, type, cmd, port, health, workdir
# Optional: 'preflight' callable returning (ok: bool, hint: str) — runs before spawn
SERVICES = [
    # ── V2 Core ──
    {
        "name": "core",
        "type": "uvicorn",
        "cmd": (
            "/Users/joneshong/workshop/.venv/bin/python3 -m uvicorn"
            f" src.main:app --host 127.0.0.1 --port {get_port('core')}"
            " --proxy-headers --env-file .env"
        ),
        "port": get_port("core"),
        "health": f"http://127.0.0.1:{get_port('core')}/docs",
        "workdir": "/Users/joneshong/workshop/core",
    },
    # ── Microservices (extracted from Core) ──
    {
        "name": "paper",
        "type": "uvicorn",
        "cmd": (
            "/Users/joneshong/workshop/services/paper/.venv/bin/python3 -m uvicorn"
            f" main:app --host 127.0.0.1 --port {get_port('paper')}"
        ),
        "port": get_port("paper"),
        "health": get("paper").health_url,
        "workdir": "/Users/joneshong/workshop/services/paper",
        "env": {"PAPER_DB_URL": "postgresql+asyncpg://joneshong:dev_12345@localhost/workshop"},
    },
    {
        "name": "intelflow",
        "type": "uvicorn",
        "cmd": (
            "/Users/joneshong/workshop/services/intelflow/.venv/bin/python3 -m uvicorn"
            f" main:app --host 127.0.0.1 --port {get_port('intelflow')}"
        ),
        "port": get_port("intelflow"),
        "health": get("intelflow").health_url,
        "workdir": "/Users/joneshong/workshop/services/intelflow",
        "env": {"INTELFLOW_DB_URL": "postgresql+asyncpg://joneshong:dev_12345@localhost/workshop"},
    },
    {
        "name": "invest",
        "type": "uvicorn",
        "cmd": (
            "/Users/joneshong/workshop/services/invest/.venv/bin/python3 -m uvicorn"
            f" main:app --host 127.0.0.1 --port {get_port('invest')}"
        ),
        "port": get_port("invest"),
        "health": get("invest").health_url,
        "workdir": "/Users/joneshong/workshop/services/invest",
        "env": {"INVEST_DB_URL": "postgresql+asyncpg://joneshong:dev_12345@localhost/workshop"},
    },
    # ── Stations ──
    {
        "name": "agent-vista",
        "type": "binary",
        "cmd": (
            "/Users/joneshong/workshop/stations/agent-vista/bin/agent-vista"
            f" --no-browser --host 127.0.0.1 --port {get_port('agent-vista')}"
        ),
        "port": get_port("agent-vista"),
        "health": get("agent-vista").health_url,
        "workdir": "/Users/joneshong/workshop/stations/agent-vista",
    },
    {
        "name": "hook-observatory",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/stations/hook-observatory/.venv/bin/python3 main.py",
        "port": get_port("hook-observatory"),
        "health": get("hook-observatory").health_url,
        "workdir": "/Users/joneshong/workshop/stations/hook-observatory",
        "env": {"HOOK_OBS_PORT": str(get_port("hook-observatory"))},
    },
    {
        "name": "session-channel",
        # Migrated 2026-05-12 from Python uvicorn → Rust channel-service.
        # Python source kept at stations/session-channel/ as reference impl.
        # Rollback: restore the uvicorn cmd below + restart.
        #   "type": "uvicorn",
        #   "cmd": "/Users/joneshong/workshop/stations/session-channel/.venv/bin/python3 main.py",
        #   "workdir": "/Users/joneshong/workshop/stations/session-channel",
        "type": "binary",
        "cmd": "/Users/joneshong/workshop/stations/session-channel-rs/target/release/channel-service",
        "port": get_port("session-channel"),
        "health": get("session-channel").health_url,
        "workdir": "/Users/joneshong/workshop/stations/session-channel-rs",
        "env": {"SESSION_CHANNEL_PORT": str(get_port("session-channel"))},
    },
    {
        "name": "sentinel",
        "type": "binary",
        "cmd": (
            "/Users/joneshong/.cargo/shared-target/release/sentinel"
            " --config /Users/joneshong/workshop/stations/sentinel/config.yaml"
        ),
        "port": get_port("sentinel"),
        "health": get("sentinel").health_url,
        "workdir": "/Users/joneshong/workshop/stations/sentinel",
    },
    # Python system-monitor retired 2026-05-01 — replaced by system-monitor-rs.
    # Rollback: revert this block (uvicorn entry) + keep stations/system-monitor/.
    # RSS 58 MB → 15 MB (省 73.8%), /status cached path 2 ms → 0.3 ms.
    {
        "name": "system-monitor",
        "type": "binary",
        "cmd": (
            "/Users/joneshong/.cargo/shared-target/release/system-monitor"
            f" serve --host 127.0.0.1 --port {get_port('system-monitor')}"
        ),
        "port": get_port("system-monitor"),
        "health": get("system-monitor").health_url,
        "workdir": "/Users/joneshong/workshop/stations/system-monitor",
    },
    # Python agent-metrics retired 2026-04-20 — replaced by agent-metrics (below).
    # Kept commented as rollback reference for 30 days, remove after 2026-05-20.
    # NOTE: maestro/task_manager engines (routes /maestro/*, /projects/*) are
    # the Phase 5b deferred scope. The Rust binary returns 404 for those paths
    # for now; if you need them, reinstate this block on a different port.
    # {
    #     "name": "agent-metrics",
    #     "type": "uvicorn",
    #     "cmd": (
    #         "/Users/joneshong/workshop/stations/agent-metrics/.venv/bin/python3"
    #         " -m agent_metrics serve"
    #     ),
    #     "port": get_port("agent-metrics"),
    #     "health": get("agent-metrics").health_url,
    #     "workdir": "/Users/joneshong/workshop/stations/agent-metrics",
    #     "env": {"AGENT_METRICS_PORT": str(get_port("agent-metrics"))},
    # },
    {
        "name": "agent-metrics",
        "type": "binary",
        "cmd": ("/Users/joneshong/.cargo/shared-target/release/agent-metrics serve"),
        "port": get_port("agent-metrics"),
        "health": get("agent-metrics").health_url,
        "workdir": "/Users/joneshong/workshop/stations/agent-metrics",
        "env": {
            "AGENT_METRICS_PORT": str(get_port("agent-metrics")),
            "AGENT_METRICS_SQLITE_PATH": "/Users/joneshong/workshop/stations/agent-metrics/data/agent_metrics.sqlite",
        },
    },
    # quota sidecar retired 2026-04-20 — Phase 5b-2 ported quota_collector
    # to agent-metrics-rs as `collectors::quota_writer` background task
    # (curl shell-out for HTTPS to bypass LuLu firewall per-build prompts).
    # Kept commented as rollback reference for 30 days, remove after 2026-05-20.
    # {
    #     "name": "agent-metrics-quota",
    #     "type": "binary",
    #     "cmd": (
    #         "/Users/joneshong/workshop/stations/agent-metrics/.venv/bin/python3"
    #         " /Users/joneshong/workshop/stations/agent-metrics/scripts/quota_sidecar.py"
    #     ),
    #     "port": 10198,
    #     "health": "http://127.0.0.1:10198/health",
    #     "workdir": "/Users/joneshong/workshop/stations/agent-metrics",
    #     "env": {
    #         "AGENT_METRICS_QUOTA_INTERVAL_S": "60",
    #         "AGENT_METRICS_QUOTA_PORT": "10198",
    #     },
    # },
    # Python auto-survey retired 2026-04-19 — replaced by auto-survey-rs (below).
    # Kept commented as rollback reference for 30 days, remove after 2026-05-19.
    # {
    #     "name": "auto-survey",
    #     "type": "uvicorn",
    #     "cmd": (
    #         "/opt/homebrew/bin/uv run --project"
    #         " /Users/joneshong/workshop/stations/auto-survey"
    #         f" auto-survey serve --host 127.0.0.1 --port {get_port('auto-survey')}"
    #     ),
    #     "port": get_port("auto-survey"),
    #     "health": get("auto-survey").health_url,
    #     "workdir": "/Users/joneshong/workshop/stations/auto-survey",
    # },
    # auto-survey: Rust binary (Python version retired 2026-04-19, cutover去綴 2026-05-12)
    # Lifecycle managed by Cronicle (ws-auto-survey-start/stop-wed/fri jobs)
    # NOT managed by workshop-launcher daemon — schedule="on-demand"
    {
        "name": "auto-survey",
        "type": "binary",
        "schedule": "on-demand",
        "cmd": (
            "/Users/joneshong/.cargo/shared-target/release/auto-survey"
            f" serve --host 127.0.0.1 --port {get_port('auto-survey')}"
        ),
        "port": get_port("auto-survey"),
        "health": get("auto-survey").health_url,
        "workdir": "/Users/joneshong/workshop/stations/auto-survey",
    },
    {
        "name": "anvil",
        "type": "uvicorn",
        "cmd": (
            "/Users/joneshong/workshop/stations/anvil/.venv/bin/python3"
            f" -m uvicorn server:app --host 127.0.0.1 --port {get_port('anvil')}"
        ),
        "port": get_port("anvil"),
        "health": get("anvil").health_url,
        "workdir": "/Users/joneshong/workshop/stations/anvil/src",
    },
    {
        "name": "stt",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/stations/stt/.venv/bin/python3 main.py",
        "port": get_port("stt"),
        "health": get("stt").health_url,
        "workdir": "/Users/joneshong/workshop/stations/stt",
        "env": {"STT_PORT": str(get_port("stt"))},
    },
    {
        "name": "ocr",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/stations/ocr/.venv/bin/python3 main.py",
        "port": get_port("ocr"),
        "health": get("ocr").health_url,
        "workdir": "/Users/joneshong/workshop/stations/ocr",
        "env": {"OCR_PORT": str(get_port("ocr"))},
    },
    {
        "name": "tts",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/stations/tts/.venv/bin/python3 main.py",
        "port": get_port("tts"),
        "health": get("tts").health_url,
        "workdir": "/Users/joneshong/workshop/stations/tts",
        "env": {"TTS_PORT": str(get_port("tts"))},
    },
    {
        "name": "vision",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/stations/vision/.venv/bin/python3 main.py",
        "port": get_port("vision"),
        "health": get("vision").health_url,
        "workdir": "/Users/joneshong/workshop/stations/vision",
        "env": {"VISION_PORT": str(get_port("vision"))},
    },
    {
        "name": "voice-gateway",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/stations/voice-gateway/.venv/bin/python3 main.py",
        "port": get_port("voice-gateway"),
        "health": get("voice-gateway").health_url,
        "workdir": "/Users/joneshong/workshop/stations/voice-gateway",
        "env": {"VOICE_GATEWAY_PORT": str(get_port("voice-gateway"))},
    },
    {
        "name": "translate",
        "type": "uvicorn",
        "cmd": "/Users/joneshong/workshop/stations/translate/.venv/bin/python3 main.py",
        "port": get_port("translate"),
        "health": get("translate").health_url,
        "workdir": "/Users/joneshong/workshop/stations/translate",
        "env": {"TRANSLATE_PORT": str(get_port("translate"))},
    },
    {
        "name": "remote-node",
        "type": "binary",
        "cmd": (
            "/Users/joneshong/.cargo/shared-target/release/remote-node"
            " --config /Users/joneshong/workshop/stations/remote-node/config.yaml"
        ),
        "port": get_port("remote-node"),
        "health": get("remote-node").health_url,
        "workdir": "/Users/joneshong/workshop/stations/remote-node",
    },
    {
        # 2026-05-10: switched to Go rewrite.
        # 2026-05-12: cutover去綴 — stations/tmux-webui-go → stations/tmux-webui.
        # Fallback: Python version in stations/_archive/tmux-webui-py/.
        "name": "tmux-webui",
        "type": "binary",
        "cmd": f"/Users/joneshong/.local/bin/tmux-webui serve --config /Users/joneshong/.config/tmux-webui/config.json --host 127.0.0.1 --port {get_port('tmux-webui')}",  # noqa: E501
        "port": get_port("tmux-webui"),
        "health": get("tmux-webui").health_url,
        "workdir": "/Users/joneshong/workshop/stations/tmux-webui",
    },
    {
        "name": "fleet",
        "type": "uvicorn",
        "cmd": (
            "/Users/joneshong/workshop/stations/fleet/.venv/bin/python -m uvicorn main:app"
            f" --host 127.0.0.1 --port {get_port('fleet')}"
        ),
        "port": get_port("fleet"),
        "health": get("fleet").health_url,
        "workdir": "/Users/joneshong/workshop/stations/fleet",
    },
    {
        "name": "capture-console",
        "type": "uvicorn",
        "cmd": f"/Users/joneshong/workshop/stations/capture-console/.venv/bin/python3 -m uvicorn server:app --host 127.0.0.1 --port {get_port('capture-console')}",  # noqa: E501
        "port": get_port("capture-console"),
        "health": get("capture-console").health_url,
        "workdir": "/Users/joneshong/workshop/stations/capture-console",
    },
    {
        "name": "cronicle",
        "type": "binary",
        "cmd": "/opt/homebrew/bin/node /Users/joneshong/workshop/vendor/cronicle/lib/main.js",
        "port": 4105,
        "health": "http://127.0.0.1:4105/api/app/ping",
        "workdir": "/Users/joneshong/workshop/vendor/cronicle",
    },
    {
        "name": "video-edit",
        "type": "uvicorn",
        "cmd": (
            "/Users/joneshong/workshop/stations/video-edit/.venv/bin/python3"
            f" -m video_edit serve --host 127.0.0.1 --port {get_port('video-edit')}"
        ),
        "port": get_port("video-edit"),
        "health": get("video-edit").health_url,
        "workdir": "/Users/joneshong/workshop/stations/video-edit",
    },
    # ── Infrastructure Tools ──
    {
        "name": "mcpproxy",
        "type": "binary",
        "cmd": "/Users/joneshong/.local/bin/mcpproxy serve --listen 127.0.0.1:8808",
        "port": 8808,
        "health": "http://127.0.0.1:8808/health",
        "workdir": "/Users/joneshong",
    },
    {
        "name": "litellm",
        "type": "binary",
        "cmd": "/Users/joneshong/.local/bin/litellm --config /Users/joneshong/.config/litellm/config.yaml --port 4000 --host 127.0.0.1",  # noqa: E501
        "port": 4000,
        "health": "http://127.0.0.1:4000",
        "workdir": "/Users/joneshong",
        "preflight": _litellm_preflight,
    },
    {
        "name": "ccr",
        "type": "binary",
        # `ccr start` self-daemonizes (CLI exits, server keeps listening).
        # workshop_services daemon_mode runs health_check_all() every 60s and
        # restarts via start_service when port is no longer listening, so the
        # self-fork pattern is fine — is_running(port) skips when already up.
        "cmd": "/Users/joneshong/Library/pnpm/ccr start",
        "port": 3456,
        "health": "http://127.0.0.1:3456",
        "workdir": "/Users/joneshong",
    },
    # ── External Sites ──
    {
        "name": "blog",
        "type": "binary",
        "cmd": "/opt/homebrew/opt/node@22/bin/node dist/server/entry.mjs",
        "port": get_port("blog"),
        "health": get("blog").health_url,
        "workdir": "/Users/joneshong/blog",
        "env": {"NODE_ENV": "production", "PORT": str(get_port("blog"))},
    },
]

# Docker containers: name, port, health_cmd
DOCKER_CONTAINERS = [
    {
        "name": "ws-infra-postgres-1",
        "port": 5432,
        "health_cmd": ["docker", "exec", "ws-infra-postgres-1", "pg_isready"],
    },
    {
        "name": "ws-infra-redis-1",
        "port": 6379,
        "health_cmd": ["docker", "exec", "ws-infra-redis-1", "redis-cli", "ping"],
    },
    {
        "name": "ws-infra-rustfs-1",
        "port": 9000,
        "health_cmd": None,  # Uses HTTP check
        "health_url": "http://127.0.0.1:9000/",
    },
    {
        "name": "ws-infra-filebrowser-1",
        "port": 8850,
        "health_cmd": None,
        "health_url": "http://127.0.0.1:8850/apps/files/health",
    },
    {
        "name": "ws-infra-lgtm-1",
        "port": 3100,
        "health_cmd": None,
        "health_url": "http://127.0.0.1:3100/api/health",
        "optional": True,  # profile-gated — only check if container exists
    },
    {
        "name": "ws-infra-bark-1",
        "port": 8090,
        "health_cmd": None,
        "health_url": "http://127.0.0.1:8090/ping",
    },
    # ntfy disabled — Bark + Web Push only
    {
        "name": "ws-infra-qdrant-1",
        "port": 6333,
        "health_cmd": None,
        "health_url": "http://127.0.0.1:6333/healthz",
    },
]

# ANSI color codes
GREEN = "\033[0;32m"
RED = "\033[0;31m"
RESET = "\033[0m"
CHECKMARK = "✓"
CROSS = "✗"


# ── Helpers ────────────────────────────────────────────────────


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def err(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] ERROR: {msg}", file=sys.stderr, flush=True)


def _container_exists(name: str) -> bool:
    """Check if a Docker container exists (running or stopped)."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.Name}}", name],
        capture_output=True,
        timeout=5,
    )
    return result.returncode == 0


def ensure_dirs() -> None:
    PID_DIR.mkdir(parents=True, exist_ok=True)
    for svc in SERVICES:
        (LOG_BASE / svc["name"]).mkdir(parents=True, exist_ok=True)
    (LOG_BASE / "launcher").mkdir(parents=True, exist_ok=True)


def _find_pids_by_port(port: int) -> list[int]:
    """Find ALL PIDs listening on a given port via lsof."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = []
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
            return pids
    except subprocess.TimeoutExpired:
        pass
    return []


def _find_pid_by_port(port: int) -> int | None:
    """Find the first PID listening on a given port (compat wrapper)."""
    pids = _find_pids_by_port(port)
    return pids[0] if pids else None


def is_running(name: str, port: int | None = None) -> int | None:
    """Return PID if service is running, else None.
    Detects zombie processes (state Z) as not running.
    Falls back to port-based detection if PID file is stale.
    Warns on duplicate instances sharing the same port.
    """
    pidfile = PID_DIR / f"{name}.pid"
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            os.kill(pid, 0)  # Test if process exists
            # Check for zombie: ps returns 'Z' state for defunct processes
            result = subprocess.run(
                ["ps", "-o", "state=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            state = result.stdout.strip()
            if state.startswith("Z"):
                log(f"{name} (PID {pid}) is zombie — cleaning up")
                pidfile.unlink(missing_ok=True)
                # Fall through to port-based detection below
            else:
                return pid
        except (ValueError, ProcessLookupError, PermissionError, subprocess.TimeoutExpired):
            pidfile.unlink(missing_ok=True)

    # Port-based fallback: detect service running without valid PID file
    if port is not None:
        pids = _find_pids_by_port(port)
        if len(pids) > 1:
            err(f"⚠️  {name} has {len(pids)} instances on :{port}: {pids}")
            # Kill extra instances, keep the newest (last PID = most recently started)
            keeper = pids[-1]
            for stale_pid in pids[:-1]:
                log(f"  Killing duplicate {name} PID {stale_pid}")
                try:
                    os.kill(stale_pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
            pids = [keeper]
        if pids:
            # Re-sync PID file
            pidfile.write_text(str(pids[0]))
            return pids[0]

    return None


def wait_for_health(url: str, timeout: int, name: str) -> bool:
    """Poll health URL until it responds or timeout."""
    elapsed = 0
    while elapsed < timeout:
        try:
            req = urllib.request.Request(url)  # noqa: S310
            with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310
                if resp.status < 500:
                    return True
        except Exception:  # noqa: S110
            pass
        time.sleep(2)
        elapsed += 2
    err(f"{name} health check failed after {timeout}s (url: {url})")
    return False


# ── Docker ─────────────────────────────────────────────────────


def wait_for_docker(timeout: int = 120) -> bool:
    log("Waiting for Docker Desktop...")
    elapsed = 0
    while elapsed < timeout:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            log("Docker is ready.")
            return True
        time.sleep(5)
        elapsed += 5
    err(f"Docker Desktop not ready after {timeout}s")
    return False


def ensure_containers() -> None:
    for container in DOCKER_CONTAINERS:
        name = container["name"]
        port = container["port"]

        # Skip optional containers (profile-gated) that don't exist
        if container.get("optional") and not _container_exists(name):
            log(f"Skipping optional container: {name} (not provisioned)")
            continue

        # Check if running
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        state = result.stdout.strip() if result.returncode == 0 else "false"

        if state != "true":
            log(f"Starting container: {name}")
            start_result = subprocess.run(
                ["docker", "start", name],
                capture_output=True,
                timeout=30,
            )
            if start_result.returncode != 0:
                err(f"Failed to start {name}")
                continue

        log(f"Checking health: {name} (:{port})")
        timeout = 30
        elapsed = 0
        healthy = False

        while elapsed < timeout:
            if container.get("health_cmd"):
                result = subprocess.run(
                    container["health_cmd"],
                    capture_output=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    healthy = True
                    break
            elif container.get("health_url"):
                try:
                    with urllib.request.urlopen(container["health_url"], timeout=3) as resp:  # noqa: S310
                        if 200 <= resp.status < 500:
                            healthy = True
                            break
                except Exception:  # noqa: S110
                    pass
            time.sleep(2)
            elapsed += 2

        if healthy:
            log(f"  {name} is healthy.")
        else:
            err(f"{name} health check timed out after {timeout}s")


# ── Service Lifecycle ──────────────────────────────────────────


def start_service(svc: dict) -> None:
    name = svc["name"]
    svc_type = svc["type"]
    port = svc["port"]
    cmd = svc["cmd"]
    health = svc["health"]
    workdir = svc["workdir"]

    pid = is_running(name, port)
    if pid is not None:
        log(f"{name} already running (PID {pid})")
        return

    preflight = svc.get("preflight")
    if preflight is not None:
        ok, hint = preflight()
        if not ok:
            err(f"{name} preflight failed — {hint}")
            return

    log_dir = LOG_BASE / name
    log_dir.mkdir(parents=True, exist_ok=True)

    log(f"Starting {name} ({svc_type}) on :{port}")

    today = date.today().strftime("%Y-%m-%d")
    stdout_log = log_dir / f"{today}.log"
    stderr_log = log_dir / f"{today}.error.log"

    import shlex

    cmd_parts = shlex.split(cmd)

    # Merge per-service env vars (e.g. port overrides) into daemon env
    run_env = _DAEMON_ENV
    svc_env = svc.get("env")
    if svc_env:
        run_env = {**_DAEMON_ENV, **svc_env}

    try:
        with open(stdout_log, "ab") as fout, open(stderr_log, "ab") as ferr:
            proc = subprocess.Popen(
                cmd_parts,
                cwd=workdir,
                stdout=fout,
                stderr=ferr,
                start_new_session=True,
                env=run_env,
            )
    except OSError as e:
        err(f"Failed to start {name}: {e}")
        return

    pid = proc.pid
    try:
        (PID_DIR / f"{name}.pid").write_text(str(pid))
    except OSError as e:
        err(f"Failed to write PID file for {name}: {e}")

    timeout = 15 if svc_type == "binary" else 30
    if wait_for_health(health, timeout, name):
        log(f"  {name} started (PID {pid})")
    else:
        err(f"  {name} may not be healthy (PID {pid})")


def _kill_tree(pid: int, sig: int) -> None:
    """Send signal to process group (covers all children spawned by start_new_session).
    Only uses killpg when pid is the group leader (pgid == pid), to avoid
    accidentally signalling an unrelated process group.
    Falls back to single-PID kill otherwise."""
    try:
        pgid = os.getpgid(pid)
        if pgid == pid:
            os.killpg(pgid, sig)
        else:
            os.kill(pid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass


def stop_service(svc: dict) -> None:
    name = svc["name"]
    pid = is_running(name, svc["port"])

    if pid is not None:
        log(f"Stopping {name} (PID {pid})")
        _kill_tree(pid, signal.SIGTERM)

        # Wait up to 10s for graceful shutdown
        waited = 0
        while waited < 10:
            try:
                os.kill(pid, 0)
                time.sleep(1)
                waited += 1
            except ProcessLookupError:
                break

        # Force kill process group if still running
        try:
            os.kill(pid, 0)
            log(f"  Force killing {name} process group (PID {pid})")
            _kill_tree(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        (PID_DIR / f"{name}.pid").unlink(missing_ok=True)
        log(f"  {name} stopped.")
    else:
        log(f"{name} is not running.")


def start_all() -> None:
    ensure_dirs()
    wait_for_docker()
    ensure_containers()
    for svc in SERVICES:
        if svc.get("schedule") == "on-demand":
            log(f"Skipping {svc['name']} (schedule=on-demand, lifecycle managed externally)")
            continue
        start_service(svc)


def stop_all() -> None:
    for svc in reversed(SERVICES):
        stop_service(svc)
    log("All app services stopped. Docker containers left running.")


# ── Log Management ─────────────────────────────────────────────


def check_log_sizes() -> None:
    today = date.today().strftime("%Y-%m-%d")
    try:
        service_dirs = list(LOG_BASE.iterdir())
    except OSError as e:
        log(f"WARNING: cannot list log directory: {e}")
        return
    for service_dir in service_dirs:
        if not service_dir.is_dir():
            continue
        for suffix in ["log", "error.log"]:
            logfile = service_dir / f"{today}.{suffix}"
            if not logfile.exists():
                continue
            try:
                size = logfile.stat().st_size
            except OSError:
                continue
            if size > LOG_MAX_SIZE:
                if suffix == "error.log":
                    base = service_dir / f"{today}"
                    ext = "error.log"
                else:
                    base = service_dir / f"{today}"  # noqa: F841
                    ext = "log"

                n = 1
                while (service_dir / f"{today}.{n}.{ext}").exists() or (
                    service_dir / f"{today}.{n}.{ext}.gz"
                ).exists():
                    n += 1

                rotated = service_dir / f"{today}.{n}.{ext}"
                shutil.copy2(logfile, rotated)
                logfile.write_bytes(b"")  # Truncate, keep fd open
                log(f"Rotated {logfile} → {rotated} (was {size} bytes)")


def compress_old_logs() -> None:
    today = date.today().strftime("%Y-%m-%d")
    import re

    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}")

    for logfile in LOG_BASE.rglob("*.log"):
        filename = logfile.name
        if not date_pattern.match(filename):
            continue
        if filename.startswith(today):
            continue
        # Compress the file
        gz_path = logfile.with_suffix(logfile.suffix + ".gz")
        try:
            with open(logfile, "rb") as f_in:
                with gzip.open(gz_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            logfile.unlink()
        except Exception:
            log(f"WARNING: gzip compression failed for {logfile}")


def cleanup_old_logs() -> None:
    cutoff = time.time() - LOG_RETAIN_DAYS * 86400
    for gz_file in LOG_BASE.rglob("*.gz"):
        try:
            if gz_file.stat().st_mtime < cutoff:
                gz_file.unlink()
        except Exception:
            log(f"WARNING: failed to remove old log {gz_file}")


# ── Health Check Loop ──────────────────────────────────────────


def health_check_docker() -> None:
    """Check Docker containers and restart any that are not running."""
    # Quick Docker availability check — skip if daemon not ready (e.g. OrbStack still resuming)
    result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
    if result.returncode != 0:
        log("Docker not ready — skipping container health check")
        return

    for container in DOCKER_CONTAINERS:
        name = container["name"]

        # Skip optional containers (profile-gated) that don't exist
        if container.get("optional") and not _container_exists(name):
            continue

        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
        )
        state = result.stdout.strip() if result.returncode == 0 else "false"
        if state != "true":
            log(f"ALERT: container {name} is down — starting...")
            start_result = subprocess.run(
                ["docker", "start", name],
                capture_output=True,
                text=True,
            )
            if start_result.returncode == 0:
                log(f"Container {name} started successfully")
            else:
                # Container might not exist (first boot) — try compose up
                log(f"docker start failed for {name}, trying compose up...")
                subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-p",
                        "ws-infra",
                        "-f",
                        "/Users/joneshong/workshop/infra/docker/docker-compose.yml",
                        "up",
                        "-d",
                    ],
                    capture_output=True,
                    env=_DAEMON_ENV,
                    timeout=120,
                )
                break  # compose up starts all — no need to check remaining


def _check_bind_addresses() -> None:
    """Verify Workshop services are not bound to 0.0.0.0 (LAN-exposed)."""
    try:
        result = subprocess.run(
            ["lsof", "-iTCP", "-sTCP:LISTEN", "-P", "-n"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return

    svc_ports = {svc["port"] for svc in SERVICES}
    for line in result.stdout.splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) < 9:
            continue
        name_col = parts[8]  # NAME column e.g. "*:8840" or "127.0.0.1:10000"
        if ":" not in name_col:
            continue
        host, port_str = name_col.rsplit(":", 1)
        try:
            port_num = int(port_str)
        except ValueError:
            continue
        if port_num not in svc_ports:
            continue
        if host == "*":
            svc_name = next(
                (s["name"] for s in SERVICES if s["port"] == port_num),
                f"port-{port_num}",
            )
            log(f"SECURITY: {svc_name} (:{port_num}) bound to 0.0.0.0 — LAN exposed!")
            # Publish alert via Redis → Core fan-out pipeline
            try:
                import json as _json
                import socket as _socket

                _payload = _json.dumps(
                    {
                        "category": "system",
                        "title": "Port Security Alert",
                        "body": f"⚠️ {svc_name} (:{port_num}) bound to 0.0.0.0",
                        "tag": f"port-security-{port_num}",
                        "severity": "critical",
                    }
                )
                _ch = "workshop:push"
                _sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                _sock.settimeout(3)
                _sock.connect(("127.0.0.1", 6379))
                _parts = f"*3\r\n$7\r\nPUBLISH\r\n${len(_ch)}\r\n{_ch}\r\n"
                _parts += f"${len(_payload)}\r\n{_payload}\r\n"
                _sock.sendall(_parts.encode())
                _sock.recv(256)
                _sock.close()
            except Exception:  # noqa: S110
                pass


# Crash-loop guard: stop restarting a service that fails _CRASH_LOOP_MAX times
# within _CRASH_LOOP_WINDOW, cool down for _CRASH_LOOP_COOLDOWN, then try again.
# Marker file lets Sentinel surface the alert.
_CRASH_LOOP_WINDOW = 300  # 5 minutes
_CRASH_LOOP_MAX = 3
_CRASH_LOOP_COOLDOWN = 600  # 10 minutes
_CRASH_LOOP_STATE: dict[str, dict] = {}
_CRASH_LOOP_MARKER_DIR = PID_DIR.parent / "workshop-crash-loop"


def _record_restart_attempt(name: str) -> bool:
    """Return False when the service is in crash-loop cooldown and should be skipped."""
    now = time.time()
    state = _CRASH_LOOP_STATE.setdefault(name, {"restarts": [], "cooldown_until": 0.0})
    if now < state["cooldown_until"]:
        return False
    state["restarts"] = [t for t in state["restarts"] if now - t < _CRASH_LOOP_WINDOW]
    state["restarts"].append(now)
    if len(state["restarts"]) >= _CRASH_LOOP_MAX:
        state["cooldown_until"] = now + _CRASH_LOOP_COOLDOWN
        state["restarts"] = []
        _write_crash_loop_marker(name)
        return False
    return True


def _write_crash_loop_marker(name: str) -> None:
    try:
        _CRASH_LOOP_MARKER_DIR.mkdir(parents=True, exist_ok=True)
        marker = _CRASH_LOOP_MARKER_DIR / f"{name}.marker"
        marker.write_text(
            f"{datetime.now().isoformat()} {name} crash-loop "
            f"(>={_CRASH_LOOP_MAX} failures in {_CRASH_LOOP_WINDOW}s) — "
            f"cooldown {_CRASH_LOOP_COOLDOWN}s\n"
        )
    except OSError:
        pass


def _clear_crash_loop_marker(name: str) -> None:
    marker = _CRASH_LOOP_MARKER_DIR / f"{name}.marker"
    marker.unlink(missing_ok=True)
    _CRASH_LOOP_STATE.pop(name, None)


def health_check_all() -> None:
    for svc in SERVICES:
        if svc.get("schedule") == "on-demand":
            continue
        name = svc["name"]
        if is_running(name, svc["port"]) is None:
            if not _record_restart_attempt(name):
                # Log once per cooldown entry (when marker was just written)
                marker = _CRASH_LOOP_MARKER_DIR / f"{name}.marker"
                if marker.exists():
                    mtime = marker.stat().st_mtime
                    if time.time() - mtime < 60:
                        err(
                            f"CRASH-LOOP: {name} failed {_CRASH_LOOP_MAX}× in "
                            f"{_CRASH_LOOP_WINDOW}s — cooling down {_CRASH_LOOP_COOLDOWN}s "
                            f"(marker: {marker})"
                        )
                continue
            log(f"ALERT: {name} is down — restarting...")
            start_service(svc)
        else:
            _clear_crash_loop_marker(name)


# ── Daemon Mode ────────────────────────────────────────────────


_ORPHAN_SCAN_INTERVAL = 300  # 5 minutes


def _scan_and_reap_orphans() -> None:
    """Scan for orphaned workshop processes and SIGTERM them."""
    try:
        reaper_script = Path(__file__).resolve().parent / "workshop_orphan_reaper.py"
        if not reaper_script.exists():
            return
        # Import find_orphans from sibling script
        import importlib.util

        spec = importlib.util.spec_from_file_location("workshop_orphan_reaper", reaper_script)
        if spec is None or spec.loader is None:
            err("Orphan reaper: failed to load module spec")
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        orphans = mod.find_orphans()
        for o in orphans:
            pid = o["pid"]
            cmd = o["command"][:80]
            log(f"Reaping orphan PID {pid} (RSS {o['rss_mb']}MB): {cmd}")
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    except Exception as exc:
        err(f"Orphan scan failed: {exc}")


def daemon_mode() -> None:
    log(f"Workshop Launcher daemon starting (PID {os.getpid()})")
    ensure_dirs()
    (PID_DIR / "launcher.pid").write_text(str(os.getpid()))

    start_all()

    last_rotate_date = ""
    last_orphan_scan = 0.0
    shutdown_requested = False

    def handle_signal(signum, frame):
        nonlocal shutdown_requested
        log("Received signal, shutting down...")
        shutdown_requested = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while not shutdown_requested:
        time.sleep(60)
        if shutdown_requested:
            break
        health_check_docker()
        health_check_all()
        _check_bind_addresses()
        check_log_sizes()

        # Periodic orphan process scan (every 5 min)
        now = time.time()
        if now - last_orphan_scan > _ORPHAN_SCAN_INTERVAL:
            last_orphan_scan = now
            _scan_and_reap_orphans()

        today = date.today().strftime("%Y-%m-%d")
        if today != last_rotate_date:
            compress_old_logs()
            cleanup_old_logs()
            last_rotate_date = today

    stop_all()
    (PID_DIR / "launcher.pid").unlink(missing_ok=True)
    sys.exit(0)


# ── Status Display ─────────────────────────────────────────────


def cmd_status() -> None:
    print()
    print("Workshop Services Status")
    print("════════════════════════════════════════")

    # Docker containers
    print("[INFRA]")
    for container in DOCKER_CONTAINERS:
        name = container["name"]
        port = container["port"]
        is_optional = container.get("optional", False)

        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", name],
            capture_output=True,
            text=True,
        )
        state = result.stdout.strip() if result.returncode == 0 else "not found"

        # Optional containers that don't exist → show as inactive, not as error
        if is_optional and state == "not found":
            print(f"  - {name:<18} Docker    :{port:<6} inactive (optional)")
            continue

        health_result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}",
                name,
            ],
            capture_output=True,
            text=True,
        )
        health = health_result.stdout.strip() if health_result.returncode == 0 else ""

        if state == "running":
            if health == "healthy":
                status_str = "running (healthy)"
            else:
                status_str = "running"
            print(f"  {CHECKMARK} {name:<18} Docker    :{port:<6} {status_str}")
        else:
            print(f"  {CROSS} {name:<18} Docker    :{port:<6} {state}")

    # App services
    print()
    print("[APP]")
    for svc in SERVICES:
        name = svc["name"]
        svc_type = svc["type"]
        port = svc["port"]
        pid = is_running(name, port)
        if pid is not None:
            print(f"  {CHECKMARK} {name:<18} {svc_type:<9} :{port:<6} running (PID {pid})")
        else:
            print(f"  {CROSS} {name:<18} {svc_type:<9} :{port:<6} stopped")

    # Launcher daemon
    print()
    print("[LAUNCHER]")
    launcher_pidfile = PID_DIR / "launcher.pid"
    if launcher_pidfile.exists():
        try:
            lpid = int(launcher_pidfile.read_text().strip())
            os.kill(lpid, 0)
            print(f"  {CHECKMARK} daemon            {'':>25} running (PID {lpid})")
        except (ValueError, ProcessLookupError, PermissionError):
            try:
                lpid = int(launcher_pidfile.read_text().strip())
                print(f"  {CROSS} daemon            {'':>25} stale pidfile (PID {lpid})")
            except (ValueError, FileNotFoundError):
                print(f"  {CROSS} daemon            {'':>25} stale pidfile")
    else:
        print(f"  {CROSS} daemon            {'':>25} not running")

    # Log summary
    print()
    print(f"[LOGS]  {LOG_BASE}/")
    today = date.today().strftime("%Y-%m-%d")
    for svc in SERVICES:
        name = svc["name"]
        log_dir = LOG_BASE / name
        today_log = log_dir / f"{today}.log"
        if today_log.exists():
            try:
                size = today_log.stat().st_size
            except OSError:
                print(f"  {name + '/':<16} (cannot read log size)")
                continue
            if size >= 1048576:
                human_size = f"{size / 1048576:.1f}M"
            elif size >= 1024:
                human_size = f"{size / 1024:.1f}K"
            else:
                human_size = f"{size}B"
            print(f"  {name + '/':<16} {today}.log ({human_size})")
        else:
            print(f"  {name + '/':<16} (no logs today)")
    print()


# ── Logs Command ───────────────────────────────────────────────


def cmd_logs(args_rest: list[str]) -> int:
    import re

    if not args_rest:
        err("Usage: workshop_services.py logs <service> [date] [--error]")
        print("Available services:")
        for svc in SERVICES:
            print(f"  - {svc['name']}")
        return 1

    service = args_rest[0]
    remaining = args_rest[1:]

    log_dir = LOG_BASE / service
    if not log_dir.is_dir():
        err(f"No log directory for service: {service}")
        return 1

    error_flag = "--error" in remaining
    suffix = "error.log" if error_flag else "log"

    # Detect date argument (YYYY-MM-DD)
    target_date = None
    for arg in remaining:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", arg):
            target_date = arg
            break

    if target_date:
        # Historical log viewing
        target = log_dir / f"{target_date}.{suffix}"
        target_gz = Path(str(target) + ".gz")

        if target.exists():
            subprocess.run(["/usr/bin/less", str(target)])
        elif target_gz.exists():
            subprocess.run(["/usr/bin/zless", str(target_gz)])
        else:
            # Check for split files
            splits = sorted(log_dir.glob(f"{target_date}.*.{suffix}")) + sorted(
                log_dir.glob(f"{target_date}.*.{suffix}.gz")
            )
            if splits:
                print("Found split files:")
                for f in splits:
                    print(str(f))
                print("---")
                # Cat all to less
                data = b""
                for f in splits:
                    if str(f).endswith(".gz"):
                        with gzip.open(f, "rb") as gz:
                            data += gz.read()
                    else:
                        data += f.read_bytes()
                proc = subprocess.Popen(["/usr/bin/less"], stdin=subprocess.PIPE)
                proc.communicate(data)
            else:
                err(f"No log found: {target}")
                return 1
    else:
        # Live tail of today's log
        today = date.today().strftime("%Y-%m-%d")
        target = log_dir / f"{today}.{suffix}"
        if not target.exists():
            log(f"Log file not yet created: {target}")
            log("Waiting for first output...")
        try:
            subprocess.run(["/usr/bin/tail", "-f", str(target)])
        except Exception:
            err(f"Cannot tail {target} — file may not exist yet.")
            return 1

    return 0


# ── Manual Rotate ──────────────────────────────────────────────


def cmd_rotate() -> None:
    log("Running manual log rotation...")
    check_log_sizes()
    compress_old_logs()
    cleanup_old_logs()
    log("Done.")


# ── Main ───────────────────────────────────────────────────────


def find_service(name: str) -> dict | None:
    """Find a service by name."""
    for svc in SERVICES:
        if svc["name"] == name:
            return svc
    return None


def print_help(prog: str) -> None:
    print(f"Usage: {prog} {{daemon|start|stop|restart|status|rotate|logs}} [service]")
    print()
    print("Commands:")
    print("  daemon          Supervisor mode (used by LaunchAgent)")
    print("  start [name]    Start all services, or a single service by name")
    print("  stop [name]     Stop all app services, or a single service by name")
    print("  restart [name]  Stop + start (all or single)")
    print("  status          Show all service status")
    print("  rotate          Manual log rotation/compression")
    print("  logs <svc>            Tail today's stdout log")
    print("  logs <svc> --error    Tail today's stderr log")
    print("  logs <svc> <date>     View historical log (auto-decompress)")
    print("  logs <svc> <date> --error  View historical error log")
    print()
    svc_names = [s["name"] for s in SERVICES]
    print(f"Services: {', '.join(svc_names)}")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "--help", "-h"):
        print_help(sys.argv[0])
        sys.exit(0)

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    if cmd == "daemon":
        daemon_mode()
    elif cmd == "start":
        ensure_dirs()
        if rest:
            svc = find_service(rest[0])
            if not svc:
                err(f"Unknown service: {rest[0]}")
                sys.exit(1)
            start_service(svc)
        else:
            start_all()
    elif cmd == "stop":
        if rest:
            svc = find_service(rest[0])
            if not svc:
                err(f"Unknown service: {rest[0]}")
                sys.exit(1)
            stop_service(svc)
        else:
            stop_all()
    elif cmd == "restart":
        if rest:
            svc = find_service(rest[0])
            if not svc:
                err(f"Unknown service: {rest[0]}")
                sys.exit(1)
            stop_service(svc)
            time.sleep(2)
            ensure_dirs()
            start_service(svc)
        else:
            stop_all()
            time.sleep(2)
            ensure_dirs()
            start_all()
    elif cmd == "status":
        cmd_status()
    elif cmd == "rotate":
        cmd_rotate()
    elif cmd == "logs":
        sys.exit(cmd_logs(rest))
    else:
        err(f"Unknown command: {cmd}")
        print_help(sys.argv[0])
        sys.exit(1)


if __name__ == "__main__":
    main()

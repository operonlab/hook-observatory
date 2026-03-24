"""Workshop Port Registry — Single Source of Truth.

All port definitions live here. Other files MUST import from this module.
DO NOT hardcode ports elsewhere — use get_url() or import constants.

Port Range Convention (10000+, for self-managed services):
    10000-10099   Core Services
    10100-10199   Stations: Infra & Ops
    10200-10299   Stations: AI & Media
    10300-10399   Stations: Business & Tools
    10500-10599   Frontend

Third-party / Docker services keep their standard ports.
"""

from __future__ import annotations

from dataclasses import dataclass

_HOST = "127.0.0.1"


@dataclass(frozen=True)
class ServicePort:
    """A registered Workshop service with its port and metadata."""

    name: str
    port: int
    group: str  # core | station-infra | station-ai | station-biz | frontend | third-party | docker
    health_path: str = "/health"
    env_var: str = ""
    nginx_path: str = ""
    optional: bool = False

    @property
    def url(self) -> str:
        return f"http://{_HOST}:{self.port}"

    @property
    def health_url(self) -> str:
        if not self.health_path:
            return ""
        return f"{self.url}{self.health_path}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Service Definitions
#
#  NOTE: Ports below are CURRENT values. Phase 4 migration will
#  switch self-managed services to 10000+ range per the convention.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PORTS: list[ServicePort] = [
    # ── Core ──
    ServicePort(
        "core", 8801, "core",
        health_path="/health", env_var="CORE_API_URL",
    ),
    # ── Stations: Infra & Ops ──
    ServicePort(
        "hook-observatory", 4100, "station-infra",
        health_path="/", env_var="HOOK_OBS_URL",
        nginx_path="/apps/hook/",
    ),
    ServicePort(
        "session-channel", 4106, "station-infra",
        health_path="/health", env_var="SESSION_CHANNEL_URL",
        nginx_path="/apps/channel/",
    ),
    ServicePort(
        "system-monitor", 9526, "station-infra",
        health_path="/", env_var="SYSTEM_MONITOR_URL",
        nginx_path="/apps/sysmon/",
    ),
    ServicePort(
        "agent-metrics", 8795, "station-infra",
        health_path="/health", env_var="AGENT_METRICS_URL",
        nginx_path="/apps/agent-metrics/",
    ),
    ServicePort(
        "capture-console", 4104, "station-infra",
        health_path="/docs", env_var="CAPTURE_CONSOLE_URL",
        nginx_path="/apps/capture/",
    ),
    ServicePort(
        "tmux-webui", 8765, "station-infra",
        health_path="/", env_var="TMUX_WEBUI_URL",
        nginx_path="/apps/tmux/",
    ),
    # ── Stations: AI & Media ──
    ServicePort(
        "stt", 4108, "station-ai",
        env_var="STT_URL", optional=True,
    ),
    ServicePort(
        "tts", 4111, "station-ai",
        env_var="TTS_URL", optional=True,
    ),
    ServicePort(
        "ocr", 4109, "station-ai",
        env_var="OCR_URL", optional=True,
    ),
    ServicePort(
        "vision", 4112, "station-ai",
        env_var="VISION_URL", optional=True,
    ),
    ServicePort(
        "voice-gateway", 4113, "station-ai",
        env_var="VOICE_GATEWAY_URL", optional=True,
        nginx_path="/apps/voice/",
    ),
    ServicePort(
        "tps", 4114, "station-ai",
        env_var="TPS_URL", optional=True,
    ),
    ServicePort(
        "video-edit", 4110, "station-ai",
        env_var="VIDEO_EDIT_URL",
        nginx_path="/apps/mlt-editor/",
    ),
    ServicePort(
        "agent-vista", 8840, "station-ai",
        health_path="/", env_var="AGENT_VISTA_URL",
        nginx_path="/apps/vista/",
    ),
    # ── Stations: Business & Tools ──
    ServicePort(
        "auto-survey", 4102, "station-biz",
        health_path="/api/people", env_var="AUTO_SURVEY_URL",
        nginx_path="/apps/survey/",
    ),
    ServicePort(
        "anvil", 4103, "station-biz",
        health_path="/docs", env_var="ANVIL_URL",
        nginx_path="/apps/anvil/",
    ),
    ServicePort(
        "blog", 4107, "station-biz",
        health_path="/zh/", env_var="BLOG_URL",
    ),
    # ── Frontend ──
    ServicePort("workbench", 3000, "frontend", health_path=""),
    # ── Third-party (keep original ports) ──
    ServicePort(
        "cronicle", 4105, "third-party",
        health_path="/api/app/ping",
        nginx_path="/apps/scheduler/",
    ),
    ServicePort(
        "litellm", 4000, "third-party",
        health_path="/health/liveliness",
    ),
    ServicePort("mcpproxy", 8808, "third-party", health_path="/health"),
    ServicePort("nginx", 8080, "third-party", health_path="/health"),
    # ── Docker (keep standard ports) ──
    ServicePort("postgres", 5432, "docker", health_path=""),
    ServicePort("redis", 6379, "docker", health_path=""),
    ServicePort("qdrant", 6333, "docker", health_path="/healthz"),
    ServicePort("rustfs", 9000, "docker", health_path="/"),
    ServicePort(
        "filebrowser", 8850, "docker",
        health_path="/apps/files/health",
    ),
    ServicePort("bark", 8090, "docker", health_path="/ping"),
    ServicePort(
        "lgtm", 3100, "docker",
        health_path="/api/health", optional=True,
    ),
]


# ── Lookup Helpers ─────────────────────────────────────────

_BY_NAME: dict[str, ServicePort] = {p.name: p for p in PORTS}


def get(name: str) -> ServicePort:
    """Get service definition by name. Raises KeyError if not found."""
    return _BY_NAME[name]


def get_url(name: str) -> str:
    """Get base URL (http://127.0.0.1:{port}) for a named service."""
    return _BY_NAME[name].url


def get_port(name: str) -> int:
    """Get port number for a named service."""
    return _BY_NAME[name].port


def by_group(group: str) -> list[ServicePort]:
    """Get all services in a group."""
    return [p for p in PORTS if p.group == group]


def all_ports() -> dict[int, str]:
    """Return {port: name} mapping — used by port_audit."""
    return {p.port: p.name for p in PORTS}


def check_conflicts() -> list[str]:
    """Detect port conflicts. Returns list of error messages (empty = OK)."""
    seen: dict[int, str] = {}
    errors = []
    for p in PORTS:
        if p.port in seen:
            errors.append(f"Port {p.port} conflict: {seen[p.port]} vs {p.name}")
        seen[p.port] = p.name
    return errors


# ── Migration Target Map (10000+ convention) ───────────────
# Reference only — will be activated in Phase 4.

MIGRATION_MAP: dict[str, int] = {
    # Core
    "core": 10000,
    # Stations: Infra & Ops
    "hook-observatory": 10100,
    "session-channel": 10101,
    "system-monitor": 10102,
    "agent-metrics": 10103,
    "capture-console": 10104,
    "tmux-webui": 10105,
    # Stations: AI & Media
    "stt": 10200,
    "tts": 10201,
    "ocr": 10202,
    "vision": 10203,
    "voice-gateway": 10204,
    "tps": 10205,
    "video-edit": 10206,
    "agent-vista": 10207,
    # Stations: Business & Tools
    "auto-survey": 10300,
    "anvil": 10301,
    "blog": 10302,
    # Frontend
    "workbench": 10500,
}

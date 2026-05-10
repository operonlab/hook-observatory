"""Workshop Port Registry — Single Source of Truth.

All port definitions are loaded at runtime from:
    shared/schemas/port_registry.yaml  (cross-language single source of truth)

Other files MUST import from this module.
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
from pathlib import Path
from typing import Any

import yaml

_HOST = "127.0.0.1"

# Path to the YAML source of truth (workshop_root/shared/schemas/port_registry.yaml)
# parents[3]: sdk_client/ → sdk-client/ → libs/ → <workshop_root>
_YAML_PATH = Path(__file__).resolve().parents[3] / "shared" / "schemas" / "port_registry.yaml"


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


def _load_from_yaml(path: Path = _YAML_PATH) -> list[ServicePort]:
    """Load service definitions from YAML file and return a list of ServicePort."""
    with path.open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)

    services: list[ServicePort] = []
    for entry in data.get("services", []):
        services.append(
            ServicePort(
                name=entry["name"],
                port=int(entry["port"]),
                group=entry["group"],
                health_path=entry.get("health_path", "/health"),
                env_var=entry.get("env_var", ""),
                nginx_path=entry.get("nginx_path", ""),
                optional=bool(entry.get("optional", False)),
            )
        )
    return services


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Service Definitions — loaded from shared/schemas/port_registry.yaml
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PORTS: list[ServicePort] = _load_from_yaml()


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


# ── Migration Map (10000+ convention) ──────────────────────
# Dynamically built from PORTS; includes only services in the 10000-10599 range.
# ACTIVE values — migration complete. Kept as reference index.

MIGRATION_MAP: dict[str, int] = {
    p.name: p.port for p in PORTS if 10000 <= p.port <= 10599
}

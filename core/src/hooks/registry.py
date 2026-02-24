"""Plugin registry — manifest loading and validation."""

from dataclasses import dataclass, field


@dataclass
class PluginManifest:
    id: str
    name: str
    version: str
    hooks: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    ui_slots: list[str] = field(default_factory=list)
    api_prefix: str = ""
    enabled: bool = False

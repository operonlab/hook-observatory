"""GPU Engine registry and protocol definition."""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

from PIL import Image


@runtime_checkable
class GPUEngine(Protocol):
    """Protocol that all GPU engines must satisfy."""

    @property
    def name(self) -> str: ...

    def is_loaded(self) -> bool: ...

    def load(self) -> None: ...

    def unload(self) -> None: ...

    def last_used(self) -> float:
        """Return timestamp of last inference call (0.0 if never used)."""
        ...

    def vram_mb(self) -> int:
        """Approximate VRAM usage in MB when loaded."""
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, GPUEngine] = {}


def _ensure_registry() -> None:
    """Lazily populate the registry on first access."""
    if _REGISTRY:
        return

    # Import engines here to avoid circular / heavy imports at module level
    from .florence2 import Florence2Engine

    _florence = Florence2Engine()
    _REGISTRY[_florence.name] = _florence


def get_engine(name: str) -> GPUEngine | None:
    """Return an engine by name, or *None* if not found."""
    _ensure_registry()
    return _REGISTRY.get(name)


def get_all_engines() -> dict[str, GPUEngine]:
    """Return the full name -> engine mapping."""
    _ensure_registry()
    return dict(_REGISTRY)

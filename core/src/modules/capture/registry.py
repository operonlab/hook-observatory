"""Adapter registry — auto-discovers capture adapters from all modules."""

from __future__ import annotations

import importlib
import logging

from .adapters import BaseCaptureAdapter

logger = logging.getLogger(__name__)

_ADAPTERS: dict[tuple[str, str], BaseCaptureAdapter] = {}
_discovered = False


def _register(adapter: BaseCaptureAdapter) -> None:
    _ADAPTERS[(adapter.module, adapter.entity_type)] = adapter


def get_adapter(module: str, entity_type: str) -> BaseCaptureAdapter | None:
    if not _discovered:
        discover_adapters()
    return _ADAPTERS.get((module, entity_type))


def list_adapters() -> list[tuple[str, str]]:
    if not _discovered:
        discover_adapters()
    return list(_ADAPTERS.keys())


# Adapter module names within core/src/modules/capture/
_ADAPTER_MODULES = [
    "finance_adapter",
    "taskflow_adapter",
    "invest_adapter",
]


def discover_adapters() -> None:
    """Import all adapter modules and register their ADAPTERS list."""
    global _discovered
    if _discovered:
        return
    _discovered = True
    for mod_name in _ADAPTER_MODULES:
        try:
            mod = importlib.import_module(f".{mod_name}", package="src.modules.capture")
            if hasattr(mod, "ADAPTERS"):
                for adapter in mod.ADAPTERS:
                    _register(adapter)
                    logger.debug(
                        "Registered adapter: %s.%s", adapter.module, adapter.entity_type
                    )
        except ImportError:
            logger.warning("Failed to import adapter module: %s", mod_name)

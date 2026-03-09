"""Adapter registry — auto-discovers capture adapters from all modules."""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import pkgutil
from pathlib import Path

from .adapters import AdapterManifest, BaseCaptureAdapter

logger = logging.getLogger(__name__)

_ADAPTERS: dict[tuple[str, str], BaseCaptureAdapter] = {}
_MANIFESTS: dict[tuple[str, str], AdapterManifest] = {}
_discovered = False


def _register(adapter: BaseCaptureAdapter) -> None:
    key = (adapter.module, adapter.entity_type)
    _ADAPTERS[key] = adapter
    if hasattr(adapter, "manifest") and callable(adapter.manifest):
        try:
            _MANIFESTS[key] = adapter.manifest()
        except Exception as e:
            logger.warning(
                "manifest_extraction_failed: %s.%s error=%s", adapter.module, adapter.entity_type, e
            )


def get_adapter(module: str, entity_type: str) -> BaseCaptureAdapter | None:
    if not _discovered:
        discover_adapters()
    return _ADAPTERS.get((module, entity_type))


def list_adapters() -> list[tuple[str, str]]:
    if not _discovered:
        discover_adapters()
    return list(_ADAPTERS.keys())


def list_manifests() -> list[AdapterManifest]:
    """Return all registered adapter manifests."""
    if not _discovered:
        discover_adapters()
    return list(_MANIFESTS.values())


def get_permissions() -> dict[str, str]:
    """Return module → permission mapping derived from registered manifests.

    Replaces the hardcoded _MODULE_WRITE_PERMS dict in routes.py.
    Each module maps to its write permission string (e.g. "finance" → "finance.write").
    When multiple entity_types exist for the same module, all must agree on permission
    (first registered wins per module key).
    """
    if not _discovered:
        discover_adapters()
    perms: dict[str, str] = {}
    for manifest in _MANIFESTS.values():
        perms.setdefault(manifest.module, manifest.permission)
    return perms


def reset_registry() -> None:
    """Reset discovery state. Useful for testing."""
    global _discovered
    _ADAPTERS.clear()
    _MANIFESTS.clear()
    _discovered = False


def discover_adapters() -> None:
    """Auto-discover adapters from two sources:

    1. Convention scan: all *_adapter.py files in this package
    2. Plugin entry points: workshop.capture.adapters group
    """
    global _discovered
    if _discovered:
        return
    _discovered = True

    # Source 1: Convention-based scan
    package_path = Path(__file__).parent
    for _finder, mod_name, _is_pkg in pkgutil.iter_modules([str(package_path)]):
        if not mod_name.endswith("_adapter"):
            continue
        try:
            mod = importlib.import_module(f".{mod_name}", package=__package__)
            adapters = getattr(mod, "ADAPTERS", [])
            for adapter in adapters:
                _register(adapter)
                logger.debug("auto_discovered_adapter: %s.%s", adapter.module, adapter.entity_type)
        except ImportError as e:
            logger.warning("adapter_import_failed: module=%s error=%s", mod_name, e)

    # Source 2: Plugin entry points (for external packages)
    try:
        eps = importlib.metadata.entry_points(group="workshop.capture.adapters")
        for ep in eps:
            try:
                adapter_list = ep.load()
                if callable(adapter_list):
                    adapter_list = adapter_list()
                for adapter in adapter_list:
                    _register(adapter)
                    logger.info("plugin_adapter_loaded: name=%s module=%s", ep.name, adapter.module)
            except Exception as e:
                logger.warning("plugin_adapter_failed: name=%s error=%s", ep.name, e)
    except Exception:
        logger.debug("no capture entry_points group defined — skipping plugin discovery")

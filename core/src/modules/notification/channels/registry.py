"""Channel registry — auto-discovers notification channels from this package."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import structlog

from .base import BaseChannel

logger = structlog.get_logger()

_CHANNELS: dict[str, BaseChannel] = {}
_discovered: bool = False


def register_channel(channel: BaseChannel) -> None:
    """Manually register a channel instance."""
    _CHANNELS[channel.name] = channel
    logger.debug("channel_registered", channel=channel.name)


def get_channel(name: str) -> BaseChannel | None:
    """Look up a channel by name. Triggers discovery on first call."""
    if not _discovered:
        discover_channels()
    return _CHANNELS.get(name)


def list_channels() -> list[str]:
    """Return sorted list of registered channel names."""
    if not _discovered:
        discover_channels()
    return sorted(_CHANNELS.keys())


def discover_channels() -> None:
    """Auto-discover channels from this package.

    Convention: any ``*_channel.py`` module in this package that exports a
    module-level ``CHANNEL`` variable (instance of BaseChannel) is registered.
    """
    global _discovered
    if _discovered:
        return
    _discovered = True

    package_path = Path(__file__).parent
    for _finder, mod_name, _is_pkg in pkgutil.iter_modules([str(package_path)]):
        if not mod_name.endswith("_channel"):
            continue
        try:
            mod = importlib.import_module(f".{mod_name}", package=__package__)
            channel = getattr(mod, "CHANNEL", None)
            if channel is not None and isinstance(channel, BaseChannel):
                register_channel(channel)
                logger.debug("channel_auto_discovered", module=mod_name, channel=channel.name)
            else:
                logger.warning(
                    "channel_missing_export",
                    module=mod_name,
                    hint="Module must export CHANNEL = <BaseChannel instance>",
                )
        except ImportError as exc:
            logger.warning("channel_import_failed", module=mod_name, error=str(exc))


def reset_registry() -> None:
    """Reset discovery state and clear all registered channels. For testing only."""
    global _discovered
    _CHANNELS.clear()
    _discovered = False

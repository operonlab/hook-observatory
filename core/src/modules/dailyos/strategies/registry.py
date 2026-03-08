"""Strategy registry — maps layout_type to strategy class."""

from __future__ import annotations

from .base import MethodStrategy
from .generic import GenericStrategy

_STRATEGY_REGISTRY: dict[str, type[MethodStrategy]] = {}


def register_strategy(layout_type: str, cls: type[MethodStrategy]) -> None:
    """Register a custom strategy class for a given layout_type."""
    _STRATEGY_REGISTRY[layout_type] = cls


def get_strategy_class(config: dict) -> type[MethodStrategy]:
    """Select strategy class. Custom strategies register by layout_type.
    Falls back to GenericStrategy for everything else."""
    # Future: register_strategy("timeline", TimeBlockingStrategy)
    # For V1, GenericStrategy handles all methods via config.
    return GenericStrategy

"""Adapter registry — maps (module, entity_type) to CaptureAdapter instances."""

from __future__ import annotations

from .adapters import BaseCaptureAdapter
from .finance_adapter import (
    InstallmentCaptureAdapter,
    SubscriptionCaptureAdapter,
    TransactionCaptureAdapter,
)

_ADAPTERS: dict[tuple[str, str], BaseCaptureAdapter] = {}


def _register(adapter: BaseCaptureAdapter) -> None:
    _ADAPTERS[(adapter.module, adapter.entity_type)] = adapter


def get_adapter(module: str, entity_type: str) -> BaseCaptureAdapter | None:
    return _ADAPTERS.get((module, entity_type))


def list_adapters() -> list[tuple[str, str]]:
    return list(_ADAPTERS.keys())


# Register built-in adapters
_register(TransactionCaptureAdapter())
_register(SubscriptionCaptureAdapter())
_register(InstallmentCaptureAdapter())

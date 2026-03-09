"""EventBus backends — pluggable strategy implementations."""

from .base import EventBackend
from .memory import InMemoryBackend

__all__ = ["EventBackend", "InMemoryBackend"]

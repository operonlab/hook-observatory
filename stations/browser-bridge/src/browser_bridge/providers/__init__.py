"""Provider registry — discover and instantiate browser providers."""
from __future__ import annotations

from ..provider import BrowserProvider
from .grok import GrokProvider
from .notebooklm import NotebookLMProvider

# All available providers
PROVIDERS: dict[str, type[BrowserProvider]] = {
    "grok": GrokProvider,
    "notebooklm": NotebookLMProvider,
}


def get_provider(name: str) -> BrowserProvider | None:
    """Get a provider instance by name."""
    cls = PROVIDERS.get(name)
    return cls() if cls else None


def list_providers() -> list[str]:
    """List all available provider names."""
    return list(PROVIDERS.keys())


def register_provider(name: str, cls: type[BrowserProvider]) -> None:
    """Register a custom provider."""
    PROVIDERS[name] = cls

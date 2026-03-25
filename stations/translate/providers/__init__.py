"""Translation provider registry."""

from __future__ import annotations

from .base import BaseTranslationProvider, TranslationResult
from .deepl import DeepLProvider
from .gemini import GeminiProvider
from .google import GoogleProvider

PROVIDERS: dict[str, type[BaseTranslationProvider]] = {
    "deepl": DeepLProvider,
    "gemini": GeminiProvider,
    "google": GoogleProvider,
}


def get_provider(name: str, **kwargs) -> BaseTranslationProvider:
    """Get provider instance by name."""
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown provider: {name}. Available: {list(PROVIDERS)}")
    return cls(**kwargs)


__all__ = [
    "PROVIDERS",
    "BaseTranslationProvider",
    "DeepLProvider",
    "GeminiProvider",
    "GoogleProvider",
    "TranslationResult",
    "get_provider",
]

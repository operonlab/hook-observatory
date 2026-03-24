"""Base translation provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TranslationResult:
    """Result from a translation provider."""

    text: str
    provider: str
    char_count: int
    estimated_cost_usd: float = 0.0


class TranslationError(Exception):
    """Base exception for translation errors."""


class QuotaExceededError(TranslationError):
    """Provider quota exhausted (e.g. DeepL monthly limit)."""


class ProviderUnavailableError(TranslationError):
    """Provider temporarily unavailable or misconfigured."""


class AuthenticationError(TranslationError):
    """API key invalid or missing."""


def normalize_lang(code: str) -> str:
    """Normalize language code: lowercase, hyphens."""
    if not code:
        return "auto"
    return code.lower().replace("_", "-")


class BaseTranslationProvider(ABC):
    """Abstract base for all translation providers."""

    name: str = "base"

    @abstractmethod
    async def translate(
        self, text: str, source_lang: str, target_lang: str
    ) -> TranslationResult:
        """Translate text. Raises TranslationError on failure."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if provider is configured and reachable."""

    def estimated_cost(self, char_count: int) -> float:
        """Estimate cost in USD for char_count characters."""
        return 0.0

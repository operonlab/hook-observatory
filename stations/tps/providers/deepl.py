"""DeepL translation provider — Tier 1 (priority)."""

from __future__ import annotations

import asyncio
import logging

from .base import (
    AuthenticationError,
    BaseTranslationProvider,
    ProviderUnavailableError,
    QuotaExceededError,
    TranslationResult,
    normalize_lang,
)

logger = logging.getLogger(__name__)

# DeepL target language mapping (requires specific format)
_TARGET_MAP = {
    "en": "EN-US",
    "en-us": "EN-US",
    "en-gb": "EN-GB",
    "zh": "ZH-HANS",
    "zh-cn": "ZH-HANS",
    "zh-hans": "ZH-HANS",
    "zh-tw": "ZH-HANT",
    "zh-hant": "ZH-HANT",
    "pt": "PT-PT",
    "pt-br": "PT-BR",
}

# DeepL source language mapping (simpler format)
_SOURCE_MAP = {
    "en": "EN",
    "en-us": "EN",
    "en-gb": "EN",
    "zh": "ZH",
    "zh-cn": "ZH",
    "zh-hans": "ZH",
    "zh-tw": "ZH",
    "zh-hant": "ZH",
}


class DeepLProvider(BaseTranslationProvider):
    """DeepL API translation. Free tier: 500K chars/month."""

    name = "deepl"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key
        self._translator = None

    def _get_translator(self):
        if self._translator is None:
            import deepl

            from config import config

            key = self._api_key or config.deepl_api_key
            if not key:
                raise AuthenticationError("TPS_DEEPL_API_KEY not set")
            self._translator = deepl.Translator(key)
        return self._translator

    def _map_target(self, lang: str) -> str:
        normalized = normalize_lang(lang)
        return _TARGET_MAP.get(normalized, normalized.upper())

    def _map_source(self, lang: str) -> str | None:
        if lang == "auto":
            return None
        normalized = normalize_lang(lang)
        return _SOURCE_MAP.get(normalized, normalized.upper())

    async def translate(
        self, text: str, source_lang: str, target_lang: str
    ) -> TranslationResult:
        import deepl

        loop = asyncio.get_running_loop()
        translator = self._get_translator()

        try:
            result = await loop.run_in_executor(
                None,
                lambda: translator.translate_text(
                    text,
                    source_lang=self._map_source(source_lang),
                    target_lang=self._map_target(target_lang),
                ),
            )
            return TranslationResult(
                text=result.text,
                provider=self.name,
                char_count=len(text),
                estimated_cost_usd=0.0,  # Free tier
            )
        except deepl.QuotaExceededException as e:
            raise QuotaExceededError(f"DeepL quota exceeded: {e}") from e
        except deepl.AuthorizationException as e:
            raise AuthenticationError(f"DeepL auth failed: {e}") from e
        except Exception as e:
            if "456" in str(e):
                raise QuotaExceededError(f"DeepL quota exceeded: {e}") from e
            raise ProviderUnavailableError(f"DeepL error: {e}") from e

    async def is_available(self) -> bool:
        try:
            loop = asyncio.get_running_loop()
            translator = self._get_translator()
            await loop.run_in_executor(None, translator.get_usage)
            return True
        except Exception:
            return False

    async def get_usage(self) -> dict:
        """Get DeepL character usage stats."""
        loop = asyncio.get_running_loop()
        translator = self._get_translator()
        usage = await loop.run_in_executor(None, translator.get_usage)
        return {
            "character_count": usage.character.count,
            "character_limit": usage.character.limit,
        }

    def estimated_cost(self, char_count: int) -> float:
        return 0.0  # Free tier

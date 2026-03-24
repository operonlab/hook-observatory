"""Translation workflow — cache-first with cascading provider fallback."""

from __future__ import annotations

import logging

from config import config
from providers import get_provider
from providers.base import (
    BaseTranslationProvider,
    TranslationError,
    normalize_lang,
)
from schemas import TranslateResponse

import db as translate_db

logger = logging.getLogger(__name__)


class TranslationWorkflow:
    """Cache → DeepL → Google cascading translator."""

    def __init__(self):
        self._providers: list[BaseTranslationProvider] = []

    def _ensure_providers(self) -> list[BaseTranslationProvider]:
        """Lazy-init providers from config, sorted by priority."""
        if not self._providers:
            sorted_cfg = sorted(
                [p for p in config.providers if p.get("enabled", True)],
                key=lambda p: p.get("priority", 99),
            )
            for pcfg in sorted_cfg:
                try:
                    self._providers.append(get_provider(pcfg["name"]))
                except ValueError as e:
                    logger.warning("Skip provider: %s", e)
        return self._providers

    async def translate(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = "zh-TW",
        preferred_provider: str | None = None,
    ) -> TranslateResponse:
        """Execute translation with cache check + cascading fallback."""
        source_lang = normalize_lang(source_lang)
        target_lang = normalize_lang(target_lang)

        # 1. Cache check
        cached = await translate_db.cache_get(text, source_lang, target_lang)
        if cached:
            return TranslateResponse(
                text=cached["text"],
                provider="cache",
                source_lang=source_lang,
                target_lang=target_lang,
                cached=True,
                char_count=len(text),
                estimated_cost_usd=0.0,
            )

        # 2. Budget check
        if await translate_db.is_budget_exceeded():
            raise TranslationError(
                f"Daily budget ${config.daily_budget_usd:.2f} exceeded"
            )

        # 3. Provider cascade
        providers = self._ensure_providers()

        # If preferred provider requested, try it first
        if preferred_provider:
            providers = sorted(
                providers,
                key=lambda p: 0 if p.name == preferred_provider else 1,
            )

        errors: list[str] = []
        for provider in providers:
            if not await provider.is_available():
                errors.append(f"{provider.name}: unavailable")
                continue

            try:
                result = await provider.translate(text, source_lang, target_lang)

                # Write to cache + record usage
                await translate_db.cache_set(
                    text, source_lang, target_lang,
                    result.text, result.provider, result.estimated_cost_usd,
                )
                await translate_db.record_usage(
                    result.provider, result.char_count, result.estimated_cost_usd
                )

                return TranslateResponse(
                    text=result.text,
                    provider=result.provider,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    cached=False,
                    char_count=result.char_count,
                    estimated_cost_usd=result.estimated_cost_usd,
                )

            except TranslationError as e:
                errors.append(f"{provider.name}: {e}")
                logger.warning("Provider %s failed: %s", provider.name, e)
                continue

        raise TranslationError(
            f"All providers failed: {'; '.join(errors) or 'no providers configured'}"
        )

    async def translate_batch(
        self,
        texts: list[str],
        source_lang: str = "auto",
        target_lang: str = "zh-TW",
    ) -> list[TranslateResponse]:
        """Translate multiple texts sequentially (respects rate limits)."""
        results = []
        for text in texts:
            result = await self.translate(text, source_lang, target_lang)
            results.append(result)
        return results


# Singleton
workflow = TranslationWorkflow()

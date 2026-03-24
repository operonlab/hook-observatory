"""Google Cloud Translation provider — Tier 2 (fallback)."""

from __future__ import annotations

import logging
import os

import httpx

from .base import (
    AuthenticationError,
    BaseTranslationProvider,
    ProviderUnavailableError,
    TranslationResult,
    normalize_lang,
)

logger = logging.getLogger(__name__)

# Language code mapping for Google Translate API v2
_LANG_MAP = {
    "zh-tw": "zh-TW",
    "zh-hant": "zh-TW",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh": "zh-CN",
    "pt-br": "pt",
}

# Google Translate API v2 (REST, key-based — simpler than v3 client library)
_API_URL = "https://translation.googleapis.com/language/translate/v2"


class GoogleProvider(BaseTranslationProvider):
    """Google Cloud Translation API v2. $20 per 1M characters after free tier."""

    name = "google"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key

    def _get_key(self) -> str:
        key = self._api_key or os.environ.get("TRANSLATE_GOOGLE_API_KEY", "")
        if not key:
            raise AuthenticationError("TRANSLATE_GOOGLE_API_KEY not set")
        return key

    def _map_lang(self, code: str) -> str:
        normalized = normalize_lang(code)
        return _LANG_MAP.get(normalized, normalized)

    async def translate(
        self, text: str, source_lang: str, target_lang: str
    ) -> TranslationResult:
        key = self._get_key()
        params: dict = {
            "key": key,
            "q": text,
            "target": self._map_lang(target_lang),
            "format": "text",
        }
        if source_lang != "auto":
            params["source"] = self._map_lang(source_lang)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(_API_URL, data=params)
                resp.raise_for_status()
                data = resp.json()

            translated = data["data"]["translations"][0]["translatedText"]
            cost = (len(text) / 1_000_000) * 20.0

            return TranslationResult(
                text=translated,
                provider=self.name,
                char_count=len(text),
                estimated_cost_usd=cost,
            )
        except httpx.HTTPStatusError as e:
            body = e.response.text[:200]
            if e.response.status_code in (401, 403):
                raise AuthenticationError(f"Google auth failed: {body}") from e
            raise ProviderUnavailableError(f"Google API error {e.response.status_code}: {body}") from e
        except Exception as e:
            raise ProviderUnavailableError(f"Google Translate error: {e}") from e

    async def is_available(self) -> bool:
        try:
            self._get_key()
            return True
        except AuthenticationError:
            return False

    def estimated_cost(self, char_count: int) -> float:
        return (char_count / 1_000_000) * 20.0

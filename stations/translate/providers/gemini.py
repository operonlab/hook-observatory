"""Gemini Flash translation provider — best for sentences and articles."""

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

# Gemini API endpoint
_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Language display names for better prompt quality
_LANG_NAMES = {
    "zh-tw": "Traditional Chinese (Taiwan)",
    "zh-hant": "Traditional Chinese",
    "zh-cn": "Simplified Chinese",
    "zh-hans": "Simplified Chinese",
    "zh": "Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "pt-br": "Brazilian Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "vi": "Vietnamese",
    "th": "Thai",
}


def _lang_name(code: str) -> str:
    normalized = normalize_lang(code)
    return _LANG_NAMES.get(normalized, code)


class GeminiProvider(BaseTranslationProvider):
    """Gemini Flash translation — excellent for sentences and articles."""

    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str = "gemini-2.5-flash"):
        self._api_key = api_key
        self._model = model

    def _get_key(self) -> str:
        key = (
            self._api_key
            or os.environ.get("TRANSLATE_GEMINI_API_KEY", "")
            or os.environ.get("TRANSLATE_GOOGLE_API_KEY", "")  # fallback to shared key
        )
        if not key:
            raise AuthenticationError("TRANSLATE_GEMINI_API_KEY not set")
        return key

    async def translate(self, text: str, source_lang: str, target_lang: str) -> TranslationResult:
        key = self._get_key()
        url = _API_URL.format(model=self._model) + f"?key={key}"

        target_name = _lang_name(target_lang)
        source_hint = ""
        if source_lang != "auto":
            source_hint = f" from {_lang_name(source_lang)}"

        prompt = (
            f"Translate the following text{source_hint} to {target_name}. "
            "Output ONLY the translated text, nothing else. "
            "Preserve the original formatting, tone, and meaning.\n\n"
            f"{text}"
        )

        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": len(text) * 3,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
                data = resp.json()

            translated = data["candidates"][0]["content"]["parts"][0]["text"].strip()

            # Estimate cost: Gemini Flash input ~$0.10/1M tokens, output ~$0.40/1M tokens
            # Rough: 4 chars ≈ 1 token
            input_tokens = len(text) / 4 + len(prompt) / 4
            output_tokens = len(translated) / 4
            cost = (input_tokens * 0.10 + output_tokens * 0.40) / 1_000_000

            return TranslationResult(
                text=translated,
                provider=self.name,
                char_count=len(text),
                estimated_cost_usd=cost,
            )
        except httpx.HTTPStatusError as e:
            body_text = e.response.text[:200]
            if e.response.status_code in (401, 403):
                raise AuthenticationError(f"Gemini auth failed: {body_text}") from e
            raise ProviderUnavailableError(
                f"Gemini API error {e.response.status_code}: {body_text}"
            ) from e
        except KeyError as e:
            raise ProviderUnavailableError(f"Gemini response parse error: {e}") from e
        except Exception as e:
            raise ProviderUnavailableError(f"Gemini error: {e}") from e

    async def is_available(self) -> bool:
        try:
            self._get_key()
            return True
        except AuthenticationError:
            return False

    def estimated_cost(self, char_count: int) -> float:
        tokens = char_count / 4
        return (tokens * 0.10 + tokens * 0.40) / 1_000_000

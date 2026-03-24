"""OpenAI Whisper API engine — cloud fallback for STT.

Best for: very long audio files, when local models aren't available.
Requires: OPENAI_API_KEY environment variable.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from . import register


def _retry_with_backoff(fn, max_retries=3, base_delay=1.0, max_delay=30.0):
    """Retry with exponential backoff."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                time.sleep(delay)
    raise last_exc


@register("openai")
class OpenAISTTEngine:
    """OpenAI Whisper API — cloud STT fallback."""

    name = "openai"

    def transcribe(self, file_path: str, language: str = "zh-TW") -> dict:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return {
                "error": "OPENAI_API_KEY not set. Export it or add to .env",
                "engine": "openai",
            }

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "openai"}

        try:
            import httpx
        except ImportError:
            return {"error": "httpx not installed", "engine": "openai"}

        lang_code = language.split("-")[0] if language else None

        def _call_api():
            with open(str(path), "rb") as f:
                files = {"file": (path.name, f, "audio/mpeg")}
                data = {"model": "whisper-1", "response_format": "verbose_json"}
                if lang_code:
                    data["language"] = lang_code

                r = httpx.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files=files,
                    data=data,
                    timeout=120,
                )
                if r.status_code >= 500:
                    r.raise_for_status()
                return r

        try:
            resp = _retry_with_backoff(_call_api, max_retries=3, base_delay=1.0, max_delay=30.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return {
                "error": f"OpenAI API error ({e.response.status_code}): {e.response.text[:300]}",
                "engine": "openai",
            }
        except Exception as e:
            return {"error": f"OpenAI API request failed: {e}", "engine": "openai"}

        result = resp.json()
        segments = []
        for s in result.get("segments", []):
            segments.append(
                {
                    "text": s.get("text", "").strip(),
                    "start": round(s.get("start", 0), 3),
                    "end": round(s.get("end", 0), 3),
                }
            )

        return {
            "text": result.get("text", "").strip(),
            "language": language,
            "segments": segments,
            "engine": "openai",
            "model": "whisper-1",
        }

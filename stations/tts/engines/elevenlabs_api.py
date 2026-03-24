"""ElevenLabs TTS API engine — highest quality cloud TTS.

Supports 32 languages, premium voices, voice cloning.
Requires: ELEVENLABS_API_KEY environment variable.
"""

from __future__ import annotations

import os
import tempfile
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

_API_BASE = "https://api.elevenlabs.io/v1"

# Default voice IDs
_DEFAULT_VOICES = {
    "sarah": "EXAVITQu4vr4xnSDxMaL",
    "roger": "CwhRBWXzGAHq8TQ4Fs17",
    "george": "JBFqnCBsd6RMkjVDRZzb",
    "alice": "Xb7hH8MSUJpSbSDYk0k2",
    "default": "EXAVITQu4vr4xnSDxMaL",  # Sarah (premade, free-tier compatible)
}


@register("elevenlabs")
class ElevenLabsEngine:
    """ElevenLabs API — highest quality TTS with voice cloning."""

    name = "elevenlabs"

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        output_path: str | None = None,
    ) -> dict:
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            return {
                "error": "ELEVENLABS_API_KEY not set. Export it or add to .env",
                "engine": "elevenlabs",
            }

        try:
            import httpx
        except ImportError:
            return {"error": "httpx not installed", "engine": "elevenlabs"}

        voice_id = _DEFAULT_VOICES.get(voice, voice)

        def _call_api():
            r = httpx.post(
                f"{_API_BASE}/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": text,
                    "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                        "speed": speed,
                    },
                },
                timeout=60,
            )
            if r.status_code >= 500:
                r.raise_for_status()
            return r

        try:
            resp = _retry_with_backoff(_call_api, max_retries=3, base_delay=1.0, max_delay=30.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return {
                "error": f"ElevenLabs API error ({e.response.status_code}): {e.response.text[:300]}",
                "engine": "elevenlabs",
            }
        except Exception as e:
            return {"error": f"ElevenLabs API failed: {e}", "engine": "elevenlabs"}

        out_path = output_path or tempfile.mktemp(suffix=".mp3", prefix="tts_11labs_")
        Path(out_path).write_bytes(resp.content)

        duration = self._get_duration_mp3(out_path)

        return {
            "audio_path": out_path,
            "duration": duration,
            "sample_rate": 44100,
            "engine": "elevenlabs",
            "model": "eleven_turbo_v2_5",
        }

    def list_voices(self) -> list[dict]:
        api_key = os.environ.get("ELEVENLABS_API_KEY")
        if not api_key:
            return []

        try:
            import httpx

            resp = httpx.get(
                f"{_API_BASE}/voices",
                headers={"xi-api-key": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "id": v["voice_id"],
                    "name": v["name"],
                    "language": "multilingual",
                }
                for v in data.get("voices", [])
            ]
        except Exception:
            return [
                {
                    "id": "21m00Tcm4TlvDq8ikWAM",
                    "name": "Rachel",
                    "language": "multilingual",
                },
                {
                    "id": "pNInz6obpgDQGcFmaJgB",
                    "name": "Adam",
                    "language": "multilingual",
                },
            ]

    @staticmethod
    def _get_duration_mp3(path: str) -> float:
        """Estimate MP3 duration from file size (rough estimate)."""
        try:
            size = Path(path).stat().st_size
            # Rough: 128kbps = 16KB/s
            return size / 16000
        except Exception:
            return 0.0

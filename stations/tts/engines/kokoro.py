"""Kokoro TTS engine — 82M parameter, most natural English voices.

54 preset voices, MLX native via mlx-audio.
Requires: pip install mlx-audio
"""

from __future__ import annotations

import logging
import tempfile
import time

from . import register

logger = logging.getLogger(__name__)

_last_used: float = 0.0
MODEL_IDLE_TTL = 300
_model = None


def _mark_used():
    global _last_used
    _last_used = time.monotonic()


def unload_model() -> bool:
    """Unload Kokoro model and free memory. Returns True if unloaded."""
    import gc

    global _model
    if _model is None:
        return False
    _model = None
    gc.collect()
    logger.info("Unloaded Kokoro model, memory freed")
    return True


def is_idle() -> bool:
    """Check if model is loaded but idle beyond TTL."""
    if _model is None:
        return False
    return (time.monotonic() - _last_used) > MODEL_IDLE_TTL


MODEL_ID = "prince-canuma/Kokoro-82M"


def _load():
    global _model
    if _model is not None:
        return
    from mlx_audio.tts import load

    logger.info("Loading Kokoro TTS model (%s)...", MODEL_ID)
    _model = load(MODEL_ID)
    logger.info("Kokoro model loaded")


@register("kokoro")
class KokoroEngine:
    """Kokoro-82M — most natural English TTS, 54 preset voices."""

    name = "kokoro"

    def synthesize(
        self,
        text: str,
        voice: str = "af_heart",
        speed: float = 1.0,
        output_path: str | None = None,
    ) -> dict:
        try:
            from mlx_audio.tts import load  # noqa: F401
        except ImportError:
            return {
                "error": "mlx-audio not installed. Run: pip install mlx-audio",
                "engine": "kokoro",
            }

        _mark_used()
        _load()

        try:
            import numpy as np
            import soundfile as sf

            out_path = output_path or tempfile.mktemp(suffix=".wav", prefix="tts_kokoro_")
            gen = _model.generate(text, voice=voice, speed=speed)

            audio_parts = []
            sample_rate = 24000
            for result in gen:
                audio_parts.append(np.array(result.audio))
                sample_rate = result.sample_rate or 24000

            full_audio = np.concatenate(audio_parts) if len(audio_parts) > 1 else audio_parts[0]
            sf.write(out_path, full_audio, sample_rate)
            duration = len(full_audio) / sample_rate

            return {
                "audio_path": out_path,
                "duration": round(duration, 3),
                "sample_rate": sample_rate,
                "engine": "kokoro",
            }
        except Exception as e:
            return {"error": f"Kokoro TTS failed: {e}", "engine": "kokoro"}

    def list_voices(self) -> list[dict]:
        return [
            {"id": "af_heart", "name": "Heart (American Female)", "language": "en"},
            {"id": "af_bella", "name": "Bella (American Female)", "language": "en"},
            {"id": "af_sarah", "name": "Sarah (American Female)", "language": "en"},
            {"id": "am_adam", "name": "Adam (American Male)", "language": "en"},
            {"id": "am_michael", "name": "Michael (American Male)", "language": "en"},
            {"id": "bf_emma", "name": "Emma (British Female)", "language": "en"},
            {"id": "bm_george", "name": "George (British Male)", "language": "en"},
        ]

    @staticmethod
    def _get_duration(path: str) -> float:
        try:
            import wave

            with wave.open(path, "rb") as w:
                return w.getnframes() / w.getframerate()
        except Exception:
            return 0.0

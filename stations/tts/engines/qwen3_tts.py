"""Qwen3-TTS engine — multilingual TTS with voice cloning.

600M params (4-bit: 1.71GB), 10 languages including zh/ja/en/ko.
Uses mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit via mlx-audio.

Known issue: split_pattern bug in mlx-audio — long text needs manual chunking.
Requires: pip install mlx-audio
"""

from __future__ import annotations

import logging
import re
import tempfile
import time

from . import register

logger = logging.getLogger(__name__)

_last_used: float = 0.0
MODEL_IDLE_TTL = 300
_model = None
MODEL_ID = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit"


def _mark_used():
    global _last_used
    _last_used = time.monotonic()


def unload_model() -> bool:
    """Unload Qwen3-TTS model and free memory. Returns True if unloaded."""
    import gc

    global _model
    if _model is None:
        return False
    _model = None
    gc.collect()
    logger.info("Unloaded Qwen3-TTS model, memory freed")
    return True


def is_idle() -> bool:
    """Check if model is loaded but idle beyond TTL."""
    if _model is None:
        return False
    return (time.monotonic() - _last_used) > MODEL_IDLE_TTL


def _load():
    global _model
    if _model is not None:
        return
    from mlx_audio.tts import load

    logger.info("Loading Qwen3-TTS model (%s)...", MODEL_ID)
    _model = load(MODEL_ID)
    logger.info("Qwen3-TTS model loaded")


@register("qwen3-tts")
class Qwen3TTSEngine:
    """Qwen3-TTS — multilingual TTS (zh/ja/en/ko), voice cloning capable."""

    name = "qwen3-tts"

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        output_path: str | None = None,
    ) -> dict:
        try:
            from mlx_audio.tts import load  # noqa: F401
        except ImportError:
            return {
                "error": "mlx-audio not installed. Run: pip install mlx-audio",
                "engine": "qwen3-tts",
            }

        _mark_used()
        _load()

        try:
            import numpy as np
            import soundfile as sf

            out_path = output_path or tempfile.mktemp(suffix=".wav", prefix="tts_qwen3_")

            # Workaround: split long text manually (split_pattern bug)
            chunks = self._split_text(text, max_chars=200)
            audio_parts = []
            sample_rate = 24000

            for chunk in chunks:
                gen = _model.generate(chunk, speed=speed)
                for result in gen:
                    audio_arr = np.array(result.audio)
                    audio_parts.append(audio_arr)
                    sample_rate = result.sample_rate or 24000

            full_audio = np.concatenate(audio_parts) if len(audio_parts) > 1 else audio_parts[0]
            sf.write(out_path, full_audio, sample_rate)

            duration = len(full_audio) / sample_rate

            return {
                "audio_path": out_path,
                "duration": duration,
                "sample_rate": 24000,
                "engine": "qwen3-tts",
            }
        except Exception as e:
            return {"error": f"Qwen3-TTS failed: {e}", "engine": "qwen3-tts"}

    def list_voices(self) -> list[dict]:
        return [
            {"id": "default", "name": "Default", "language": "multilingual"},
        ]

    @staticmethod
    def _split_text(text: str, max_chars: int = 200) -> list[str]:
        """Split text into chunks at sentence boundaries."""
        if len(text) <= max_chars:
            return [text]

        sentences = re.split(r"(?<=[。！？.!?\n])", text)
        chunks = []
        current = ""

        for sent in sentences:
            if not sent.strip():
                continue
            if len(current) + len(sent) > max_chars and current:
                chunks.append(current.strip())
                current = sent
            else:
                current += sent

        if current.strip():
            chunks.append(current.strip())

        return chunks if chunks else [text]

    @staticmethod
    def _concat_wavs(paths: list[str], output: str):
        """Concatenate multiple WAV files into one."""
        import wave

        if not paths:
            return

        with wave.open(paths[0], "rb") as first:
            params = first.getparams()

        with wave.open(output, "wb") as out:
            out.setparams(params)
            for p in paths:
                with wave.open(p, "rb") as w:
                    out.writeframes(w.readframes(w.getnframes()))

    @staticmethod
    def _get_duration(path: str) -> float:
        try:
            import wave

            with wave.open(path, "rb") as w:
                return w.getnframes() / w.getframerate()
        except Exception:
            return 0.0

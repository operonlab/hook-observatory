"""Qwen3-ASR engine — best Chinese STT, 52 languages + Cantonese dialects.

1.7B params (8-bit: 2.46GB), measurably superior to Whisper on Chinese
(WER 4.97% vs 9.86% on WenetSpeech). Supports 30 languages + 22 dialects.

Uses mlx-community/Qwen3-ASR-1.7B-8bit via mlx-audio.
Requires: pip install mlx-audio
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from . import register

logger = logging.getLogger(__name__)

_last_used: float = 0.0
MODEL_IDLE_TTL = 300  # 5 minutes
_model = None
MODEL_ID = "mlx-community/Qwen3-ASR-1.7B-8bit"


def _mark_used():
    global _last_used
    _last_used = time.monotonic()


def unload_model() -> bool:
    import gc

    global _model
    if _model is None:
        return False
    _model = None
    gc.collect()
    logger.info("Unloaded Qwen3-ASR model, memory freed")
    return True


def is_idle() -> bool:
    if _model is None:
        return False
    return (time.monotonic() - _last_used) > MODEL_IDLE_TTL


def _load():
    global _model
    if _model is not None:
        return
    from mlx_audio.stt import load

    logger.info("Loading Qwen3-ASR model (%s)...", MODEL_ID)
    _model = load(MODEL_ID)
    logger.info("Qwen3-ASR model loaded")


@register("qwen3-asr")
class Qwen3ASREngine:
    """Qwen3-ASR — best Chinese ASR, 52 languages, Cantonese support."""

    name = "qwen3-asr"

    def transcribe(self, file_path: str, language: str = "zh-TW") -> dict:
        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "qwen3-asr"}

        try:
            from mlx_audio.stt import load  # noqa: F401
        except ImportError:
            return {
                "error": "mlx-audio not installed. Run: pip install mlx-audio",
                "engine": "qwen3-asr",
            }

        _mark_used()
        _load()

        try:
            result = _model.generate(str(path))

            # STTOutput has .text, .segments, .language, .total_time
            text = result.text.strip() if hasattr(result, "text") else ""
            segments = []
            if hasattr(result, "segments") and result.segments:
                for s in result.segments:
                    seg = {}
                    if isinstance(s, dict):
                        seg = {
                            "text": s.get("text", "").strip(),
                            "start": round(s.get("start", 0), 3),
                            "end": round(s.get("end", 0), 3),
                        }
                    elif hasattr(s, "text"):
                        seg = {"text": s.text.strip()}
                        if hasattr(s, "start"):
                            seg["start"] = round(s.start, 3)
                        if hasattr(s, "end"):
                            seg["end"] = round(s.end, 3)
                    if seg.get("text"):
                        segments.append(seg)

            meta = {
                "text": text,
                "language": language,
                "segments": segments,
                "engine": "qwen3-asr",
                "model": MODEL_ID,
            }
            if hasattr(result, "total_time"):
                meta["processing_time"] = round(result.total_time, 3)

            return meta
        except Exception as e:
            return {"error": f"Qwen3-ASR failed: {e}", "engine": "qwen3-asr"}

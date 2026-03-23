"""MLX Whisper engine — Apple Silicon optimized speech recognition.

Best overall STT engine: 809M params, ~4GB memory, 99+ languages.
Uses mlx-community/whisper-large-v3-turbo for best speed/quality balance.

Requires: pip install mlx-whisper
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from . import register

logger = logging.getLogger(__name__)

# Lazy singleton — auto-unload after idle timeout
_last_used: float = 0.0
MODEL_IDLE_TTL = 300  # 5 minutes
_model_loaded: bool = False
MODEL_ID = "mlx-community/whisper-large-v3-turbo"


def _mark_used():
    global _last_used
    _last_used = time.monotonic()


def unload_model() -> bool:
    """Unload cached model and free memory."""
    import gc

    global _model_loaded
    if not _model_loaded:
        return False
    _model_loaded = False
    gc.collect()
    logger.info("Unloaded mlx-whisper model, memory freed")
    return True


def is_idle() -> bool:
    if not _model_loaded:
        return False
    return (time.monotonic() - _last_used) > MODEL_IDLE_TTL


@register("mlx-whisper")
class MLXWhisperEngine:
    """MLX Whisper engine — Apple Silicon optimized, 99+ languages."""

    name = "mlx-whisper"

    def transcribe(self, file_path: str, language: str = "zh-TW") -> dict:
        global _model_loaded

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "mlx-whisper"}

        try:
            import mlx_whisper
        except ImportError:
            return {
                "error": "mlx-whisper not installed. Run: pip install mlx-whisper",
                "engine": "mlx-whisper",
            }

        _mark_used()
        _model_loaded = True

        try:
            # mlx_whisper uses ISO 639-1 codes: "zh-TW" → "zh"
            lang_code = language.split("-")[0] if language else None
            result = mlx_whisper.transcribe(
                str(path),
                path_or_hf_repo=MODEL_ID,
                language=lang_code,
            )
        except Exception as e:
            return {"error": f"mlx-whisper failed: {e}", "engine": "mlx-whisper"}

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
            "engine": "mlx-whisper",
        }

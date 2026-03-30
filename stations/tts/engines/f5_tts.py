"""F5-TTS engine — flow-matching based voice cloning TTS.

Zero-shot voice cloning from a reference audio sample.
Requires: pip install f5-tts torch torchaudio
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

ALFRED_REF = "/Users/joneshong/workshop/lab/rvc-mlx/datasets/alfred/clean_final/real_01_clean.wav"


def _builtin_ref_en() -> str:
    """Return path to F5-TTS built-in English reference audio."""
    from importlib.resources import files

    return str(files("f5_tts").joinpath("infer/examples/basic/basic_ref_en.wav"))


# Voice ID -> reference audio path mapping (None = resolve at runtime via _builtin_ref_en)
_VOICE_MAP: dict[str, str | None] = {
    "default": None,  # Resolved to built-in reference at synthesis time
    "alfred": ALFRED_REF,
}


def _mark_used():
    global _last_used
    _last_used = time.monotonic()


def unload_model() -> bool:
    """Unload F5-TTS model and free memory. Returns True if unloaded."""
    import gc

    global _model
    if _model is None:
        return False
    _model = None
    gc.collect()
    try:
        import torch

        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass
    logger.info("Unloaded F5-TTS model, memory freed")
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
    from f5_tts.api import F5TTS

    logger.info("Loading F5-TTS model (device=mps)...")
    _model = F5TTS(device="mps")
    logger.info("F5-TTS model loaded (sample_rate=%d)", _model.target_sample_rate)


def _resolve_ref(voice: str) -> str:
    """Resolve voice ID to reference audio path.

    - Known voice IDs map to preset paths.
    - 'default' uses F5-TTS built-in English reference.
    - Absolute paths starting with '/' are used directly.
    """
    if voice in _VOICE_MAP:
        path = _VOICE_MAP[voice]
        if path is None:
            return _builtin_ref_en()
        return path
    if voice.startswith("/"):
        return voice
    logger.warning("Unknown voice '%s', falling back to default", voice)
    return _builtin_ref_en()


@register("f5-tts")
class F5TTSEngine:
    """F5-TTS — flow-matching voice cloning TTS with zero-shot capability."""

    name = "f5-tts"

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        output_path: str | None = None,
    ) -> dict:
        try:
            from f5_tts.api import F5TTS  # noqa: F401
        except ImportError:
            return {
                "error": "f5-tts not installed. Run: pip install f5-tts",
                "engine": "f5-tts",
            }

        _mark_used()
        _load()

        try:
            import numpy as np
            import soundfile as sf

            from . import to_simplified

            out_path = output_path or tempfile.mktemp(suffix=".wav", prefix="tts_f5_")
            ref_file = _resolve_ref(voice)
            gen_text = to_simplified(text)

            wav, sr, _spec = _model.infer(
                ref_file=ref_file or "",
                ref_text="",  # empty = auto-transcribe
                gen_text=gen_text,
                speed=speed,
                show_info=logger.debug,
            )

            # wav may be torch.Tensor or numpy array
            if hasattr(wav, "numpy"):
                wav = wav.numpy()
            wav = np.asarray(wav, dtype=np.float32)

            sample_rate = sr or _model.target_sample_rate
            sf.write(out_path, wav, sample_rate)
            duration = len(wav) / sample_rate

            return {
                "audio_path": out_path,
                "duration": round(duration, 3),
                "sample_rate": sample_rate,
                "engine": "f5-tts",
            }
        except Exception as e:
            logger.exception("F5-TTS synthesis failed")
            return {"error": f"F5-TTS failed: {e}", "engine": "f5-tts"}

    def list_voices(self) -> list[dict]:
        return [
            {"id": "default", "name": "Default", "language": "en"},
            {"id": "alfred", "name": "Alfred Pennyworth", "language": "en"},
        ]

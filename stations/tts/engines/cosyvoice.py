"""CosyVoice 2 engine — zero-shot voice cloning TTS from Alibaba FunAudioLLM.

Zero-shot voice cloning with reference audio, cross-lingual support.
Requires: CosyVoice repo cloned at ~/workshop/lab/cosyvoice
Model: iic/CosyVoice2-0.5B (auto-downloaded via modelscope on first use)
"""

from __future__ import annotations

import logging
import sys
import tempfile
import time

from . import register

logger = logging.getLogger(__name__)

_last_used: float = 0.0
MODEL_IDLE_TTL = 300
_model = None

COSYVOICE_REPO = "/Users/joneshong/workshop/lab/cosyvoice"
COSYVOICE_MATCHA = "/Users/joneshong/workshop/lab/cosyvoice/third_party/Matcha-TTS"
COSYVOICE_MODEL_ID = "iic/CosyVoice2-0.5B"

ALFRED_REF = "/tmp/alfred_ref_cosyvoice.wav"  # 5s, 22050Hz, resampled from clean_final

# Voice ID -> (ref_audio_path, ref_text)
# ref_text is optional hint for zero-shot; empty string = auto-transcribe
_VOICE_MAP: dict[str, tuple[str | None, str]] = {
    "default": (None, ""),  # Uses cross-lingual mode (no ref needed beyond prompt wav)
    "alfred": (ALFRED_REF, ""),
}


def _mark_used():
    global _last_used
    _last_used = time.monotonic()


def unload_model() -> bool:
    """Unload CosyVoice model and free memory. Returns True if unloaded."""
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
    logger.info("Unloaded CosyVoice model, memory freed")
    return True


def is_idle() -> bool:
    """Check if model is loaded but idle beyond TTL."""
    if _model is None:
        return False
    return (time.monotonic() - _last_used) > MODEL_IDLE_TTL


def _ensure_path():
    """Ensure CosyVoice repo is on sys.path for imports."""
    for p in [COSYVOICE_REPO, COSYVOICE_MATCHA]:
        if p not in sys.path:
            sys.path.insert(0, p)


def _load():
    global _model
    if _model is not None:
        return

    _ensure_path()
    from cosyvoice.cli.cosyvoice import CosyVoice2

    logger.info("Loading CosyVoice2 model '%s' ...", COSYVOICE_MODEL_ID)
    _model = CosyVoice2(COSYVOICE_MODEL_ID)
    logger.info("CosyVoice2 model loaded (sample_rate=%d)", _model.sample_rate)


def _resolve_ref(voice: str) -> tuple[str | None, str]:
    """Resolve voice ID to (ref_audio_path, ref_text).

    - Known voice IDs map to preset paths.
    - 'default' has no preset ref audio (will use cross-lingual mode).
    - Absolute paths starting with '/' are used directly as ref audio.
    """
    if voice in _VOICE_MAP:
        return _VOICE_MAP[voice]
    if voice.startswith("/"):
        return (voice, "")
    logger.warning("Unknown voice '%s', falling back to default", voice)
    return _VOICE_MAP["default"]


@register("cosyvoice")
class CosyVoiceEngine:
    """CosyVoice 2 -- zero-shot voice cloning TTS with cross-lingual support."""

    name = "cosyvoice"

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        output_path: str | None = None,
    ) -> dict:
        try:
            _ensure_path()
            from cosyvoice.cli.cosyvoice import CosyVoice2  # noqa: F401
        except ImportError:
            return {
                "error": (
                    f"CosyVoice not available. Clone repo to {COSYVOICE_REPO} and install deps."
                ),
                "engine": "cosyvoice",
            }

        _mark_used()
        _load()

        try:
            import numpy as np
            import soundfile as sf
            import torch

            from . import to_simplified

            out_path = output_path or tempfile.mktemp(suffix=".wav", prefix="tts_cosyvoice_")
            ref_audio, ref_text = _resolve_ref(voice)
            text = to_simplified(text)

            # Collect all chunks from the generator
            chunks = []

            if ref_audio is not None:
                # Detect if cross-lingual: ref is English but text is Chinese
                is_cross_lingual = (
                    ref_text
                    and not any("\u4e00" <= c <= "\u9fff" for c in ref_text)
                    and any("\u4e00" <= c <= "\u9fff" for c in text)
                )

                if is_cross_lingual:
                    # Cross-lingual: English ref + Chinese text
                    # Must use inference_cross_lingual with <|zh|> tag
                    logger.info(
                        "CosyVoice cross-lingual synthesis (ref=%s)",
                        ref_audio,
                    )
                    for chunk in _model.inference_cross_lingual(
                        f"<|zh|>{text}",
                        ref_audio,
                        stream=False,
                        speed=speed,
                    ):
                        chunks.append(chunk["tts_speech"])
                else:
                    # Same-language zero-shot
                    logger.info(
                        "CosyVoice zero-shot synthesis (ref=%s)",
                        ref_audio,
                    )
                    for chunk in _model.inference_zero_shot(
                        text,
                        ref_text,
                        ref_audio,
                        stream=False,
                        speed=speed,
                    ):
                        chunks.append(chunk["tts_speech"])
            else:
                # No ref audio — use cross-lingual with Alfred fallback
                fallback_ref = ALFRED_REF
                logger.info("CosyVoice cross-lingual synthesis (fallback ref)")
                for chunk in _model.inference_cross_lingual(
                    f"<|zh|>{text}",
                    fallback_ref,
                    stream=False,
                    speed=speed,
                ):
                    chunks.append(chunk["tts_speech"])

            if not chunks:
                return {
                    "error": "CosyVoice produced no output",
                    "engine": "cosyvoice",
                }

            # Concatenate all chunks along time axis
            wav_tensor = torch.cat(chunks, dim=-1)

            # Convert to numpy for saving
            wav = wav_tensor.squeeze().cpu().numpy()
            wav = np.asarray(wav, dtype=np.float32)

            sample_rate = _model.sample_rate
            sf.write(out_path, wav, sample_rate)
            duration = len(wav) / sample_rate

            return {
                "audio_path": out_path,
                "duration": round(duration, 3),
                "sample_rate": sample_rate,
                "engine": "cosyvoice",
            }
        except Exception as e:
            logger.exception("CosyVoice synthesis failed")
            return {"error": f"CosyVoice failed: {e}", "engine": "cosyvoice"}

    def list_voices(self) -> list[dict]:
        return [
            {"id": "default", "name": "Default (cross-lingual)", "language": "multi"},
            {"id": "alfred", "name": "Alfred Pennyworth", "language": "multi"},
        ]

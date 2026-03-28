"""VAD-based silence trimming operator using sherpa-onnx Silero VAD."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from . import _default_model_dir, register

logger = logging.getLogger(__name__)


@register("vad-trim")
class VadTrimOp:
    name = "vad-trim"
    input_keys = ("audio", "sample_rate")
    output_keys = ("audio",)

    def __init__(
        self,
        threshold: float = 0.5,
        min_silence_duration: float = 0.5,
        min_speech_duration: float = 0.25,
        model_dir: Path | str | None = None,
    ):
        self.threshold = threshold
        self.min_silence_duration = min_silence_duration
        self.min_speech_duration = min_speech_duration
        self._model_dir = Path(model_dir) if model_dir else _default_model_dir()

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        import sherpa_onnx

        audio = ctx["audio"]
        sr = ctx["sample_rate"]

        model_path = self._model_dir / "silero_vad.onnx"
        if not model_path.exists():
            raise FileNotFoundError(
                f"Silero VAD model not found at {model_path}. "
                "Run: python stations/stt/scripts/download_models.py"
                " or set WORKSHOP_AUDIO_MODELS env var."
            )

        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(model_path)
        config.silero_vad.threshold = self.threshold
        config.silero_vad.min_silence_duration = self.min_silence_duration
        config.silero_vad.min_speech_duration = self.min_speech_duration
        config.sample_rate = sr

        # Chunk-based VAD: feed audio in small chunks and track speech regions
        # sherpa-onnx 1.12+ returns empty samples from front property when
        # audio is fed all at once, so we use is_speech_detected() per-chunk.
        vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=300)
        chunk_size = 512
        speech_mask = np.zeros(len(audio), dtype=bool)

        for i in range(0, len(audio), chunk_size):
            chunk = audio[i : i + chunk_size]
            if len(chunk) < chunk_size:
                chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
            vad.accept_waveform(chunk.astype(np.float32))
            if vad.is_speech_detected():
                end = min(i + chunk_size, len(audio))
                speech_mask[i:end] = True

        orig_dur = len(audio) / sr

        if not np.any(speech_mask):
            logger.warning("VAD: no speech detected, keeping original audio (%.1fs)", orig_dur)
            return ctx

        # Find first and last speech sample to trim silence from edges
        speech_indices = np.where(speech_mask)[0]
        start = max(0, speech_indices[0] - int(sr * 0.1))  # 100ms padding
        end = min(len(audio), speech_indices[-1] + int(sr * 0.1))
        trimmed = audio[start:end]

        trimmed_dur = len(trimmed) / sr
        logger.info(
            "VAD trim: %.1fs -> %.1fs (removed %.1fs silence)",
            orig_dur,
            trimmed_dur,
            orig_dur - trimmed_dur,
        )
        ctx["audio"] = trimmed
        return ctx

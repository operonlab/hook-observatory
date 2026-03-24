"""VAD operator — Silero VAD via sherpa-onnx."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import sherpa_onnx

logger = logging.getLogger(__name__)


class VadGate:
    """Silero VAD wrapper — detects speech activity in audio chunks.

    Uses sherpa-onnx VoiceActivityDetector with CoreML EP for ANE acceleration.
    """

    def __init__(
        self,
        model_path: str | Path,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        min_silence_duration: float = 0.5,
        min_speech_duration: float = 0.25,
    ):
        model_path = str(Path(model_path).resolve())
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = model_path
        config.silero_vad.threshold = threshold
        config.silero_vad.min_silence_duration = min_silence_duration
        config.silero_vad.min_speech_duration = min_speech_duration
        config.sample_rate = sample_rate
        config.provider = "coreml"

        self._vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)
        self._sample_rate = sample_rate
        logger.info("vad_loaded: model=%s threshold=%.2f", model_path, threshold)

    def accept(self, samples: np.ndarray) -> bool:
        """Feed audio chunk, return True if speech is detected."""
        self._vad.accept_waveform(samples)
        return self._vad.is_speech()

    def get_speech_segment(self) -> np.ndarray | None:
        """Pop a completed speech segment (after silence detected), or None."""
        if not self._vad.empty():
            segment = self._vad.front()
            self._vad.pop()
            return np.array(segment.samples, dtype=np.float32)
        return None

    def flush(self) -> None:
        """Flush VAD state, forcing end-of-speech."""
        self._vad.flush()

    def reset(self) -> None:
        """Clear all internal state."""
        self._vad.clear()

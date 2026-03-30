"""Speech emotion recognition operator — HuggingFace transformers backend.

Lazy-loads the model on first call to avoid import-time overhead.

Usage:
    from audio_ops.emotion import EmotionOp

    op = EmotionOp()
    ctx = op({"audio": audio_array, "sample_rate": 16000})
    # ctx["emotions"] → [{"label": "happy", "score": 0.85, "all": [...]}]

    # With diarization segments → per-segment emotion:
    ctx = op({"audio": audio_array, "sample_rate": 16000,
              "diarization_segments": [{"start": 0.0, "end": 3.2, "speaker": "S0"}]})
    # ctx["emotions"] → [{"label": "angry", "score": 0.72,
    #   "start": 0.0, "end": 3.2, "speaker": "S0", "all": [...]}]
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from . import register

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition"
_TARGET_SR = 16000
_MIN_SAMPLES = 1600  # 100ms at 16kHz — shorter clips produce garbage


@register("emotion")
class EmotionOp:
    """Classify emotions from audio using a HuggingFace audio-classification model.

    Input:  ctx["audio"] (np.ndarray float32), ctx["sample_rate"] (int)
    Output: ctx["emotions"] (list[dict]) — per-segment or whole-file results

    If ctx["diarization_segments"] exists, runs per-segment analysis.
    """

    name = "emotion"
    input_keys = ("audio", "sample_rate")
    output_keys = ("emotions",)

    def __init__(self, model: str = _DEFAULT_MODEL, top_k: int = 3, device: str = "cpu"):
        self._model_name = model
        self._top_k = top_k
        self._device = device
        self._pipe = None

    def _get_pipe(self):
        if self._pipe is None:
            from transformers import pipeline

            self._pipe = pipeline(
                "audio-classification",
                model=self._model_name,
                device=self._device,
                top_k=self._top_k,
            )
            logger.info("EmotionOp: loaded model %s on %s", self._model_name, self._device)
        return self._pipe

    def _classify(self, audio: np.ndarray, sr: int) -> dict[str, Any]:
        """Classify a single audio segment, return {label, score, all}."""
        if len(audio) < _MIN_SAMPLES:
            return {"label": "unknown", "score": 0.0, "all": []}

        pipe = self._get_pipe()
        result = pipe({"raw": audio, "sampling_rate": sr})
        top = result[0]
        return {
            "label": top["label"],
            "score": round(top["score"], 4),
            "all": [{"label": r["label"], "score": round(r["score"], 4)} for r in result],
        }

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        audio = ctx["audio"]
        sr = ctx["sample_rate"]

        # Resample to 16kHz if needed (wav2vec2 models expect 16kHz)
        if sr != _TARGET_SR:
            from scipy.signal import resample

            num_samples = int(len(audio) * _TARGET_SR / sr)
            audio = resample(audio, num_samples).astype(np.float32)
            sr = _TARGET_SR

        segments = ctx.get("diarization_segments")

        if segments:
            # Per-segment emotion analysis
            emotions = []
            for seg in segments:
                start_sample = int(seg["start"] * sr)
                end_sample = int(seg["end"] * sr)
                segment_audio = audio[start_sample:end_sample]

                result = self._classify(segment_audio, sr)
                result["start"] = seg["start"]
                result["end"] = seg["end"]
                if "speaker" in seg:
                    result["speaker"] = seg["speaker"]
                emotions.append(result)

            logger.info(
                "EmotionOp: analyzed %d segments — top emotions: %s",
                len(emotions),
                ", ".join(f'{e["label"]}({e["score"]:.0%})' for e in emotions[:5]),
            )
        else:
            # Whole-file analysis
            result = self._classify(audio, sr)
            emotions = [result]
            logger.info(
                "EmotionOp: whole-file → %s (%.0f%%)",
                result["label"], result["score"] * 100,
            )

        ctx["emotions"] = emotions
        return ctx

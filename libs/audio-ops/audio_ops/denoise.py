"""Denoise operator using sherpa-onnx GTCRN model."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from . import _default_model_dir, register

logger = logging.getLogger(__name__)

_denoiser = None


def _get_denoiser(model_dir: Path):
    global _denoiser
    if _denoiser is not None:
        return _denoiser

    import sherpa_onnx

    model_path = model_dir / "gtcrn_simple.onnx"
    if not model_path.exists():
        raise FileNotFoundError(
            f"GTCRN model not found at {model_path}. "
            "Run: python stations/stt/scripts/download_models.py"
            " or set WORKSHOP_AUDIO_MODELS env var."
        )

    config = sherpa_onnx.OfflineSpeechDenoiserConfig()
    config.model.gtcrn.model = str(model_path)
    config.model.num_threads = 2

    for provider in ("coreml", "cpu"):
        config.model.provider = provider
        try:
            _denoiser = sherpa_onnx.OfflineSpeechDenoiser(config)
            logger.info("Denoiser loaded: GTCRN, provider=%s", provider)
            return _denoiser
        except Exception:
            if provider == "cpu":
                raise
            logger.warning("CoreML provider failed, falling back to CPU")

    return _denoiser


@register("denoise")
class DenoiseOp:
    name = "denoise"
    input_keys = ("audio", "sample_rate")
    output_keys = ("audio", "sample_rate")

    def __init__(self, model_dir: Path | str | None = None):
        self._model_dir = Path(model_dir) if model_dir else _default_model_dir()

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        denoiser = _get_denoiser(self._model_dir)
        audio = ctx["audio"]
        sr = ctx["sample_rate"]

        result = denoiser.run(audio.tolist(), sr)

        ctx["audio"] = np.array(result.samples, dtype=np.float32)
        ctx["sample_rate"] = result.sample_rate
        logger.info(
            "Denoise: sr=%d->%d, samples=%d->%d",
            sr,
            result.sample_rate,
            len(audio),
            len(result.samples),
        )
        return ctx

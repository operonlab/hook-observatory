"""Audio peak normalization operator."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from . import register

logger = logging.getLogger(__name__)


@register("normalize")
class NormalizeOp:
    name = "normalize"
    input_keys = ("audio",)
    output_keys = ("audio",)

    def __init__(self, target_db: float = -3.0):
        self.target_db = target_db

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        audio = ctx["audio"]
        peak = np.max(np.abs(audio))

        if peak < 1e-10:
            logger.warning("Normalize: audio is silent, skipping")
            return ctx

        current_db = 20 * np.log10(peak)
        gain_db = self.target_db - current_db
        gain_linear = 10 ** (gain_db / 20)

        ctx["audio"] = np.clip(audio * gain_linear, -1.0, 1.0)
        logger.info(
            "Normalize: peak %.1f dB -> %.1f dB (gain %.2fx)",
            current_db,
            self.target_db,
            gain_linear,
        )
        return ctx

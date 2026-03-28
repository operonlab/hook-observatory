"""CLAHE (Contrast Limited Adaptive Histogram Equalization) operator.

Extracted from ``stations/ocr/preprocessing.py`` lines 78-80.
OpenCV-only — no Pillow fallback (CLAHE has no PIL equivalent).
"""

from __future__ import annotations

import logging
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("clahe")
class ClaheOp:
    name = "clahe"
    input_keys = ("image",)
    output_keys = ("image",)

    def __init__(self, clip_limit: float = 3.0, tile_size: int = 8):
        self._clip_limit = clip_limit
        self._tile_size = int(tile_size)

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        try:
            import cv2
        except ImportError:
            logger.warning("CLAHE: cv2 not available, skipping (no Pillow fallback)")
            return ctx

        img = ctx["image"]

        # CLAHE requires single-channel input — auto-convert if needed
        if img.ndim == 3:
            logger.info("CLAHE: input is colour, auto-converting to grayscale first")
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            ctx["color_space"] = "gray"

        clahe = cv2.createCLAHE(
            clipLimit=self._clip_limit,
            tileGridSize=(self._tile_size, self._tile_size),
        )
        ctx["image"] = clahe.apply(img)
        logger.info(
            "CLAHE: clip_limit=%.1f, tile_size=%d, shape=%s",
            self._clip_limit,
            self._tile_size,
            img.shape,
        )
        return ctx

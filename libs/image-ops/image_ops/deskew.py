"""Deskew operator — straighten rotated document scans.

Extracted from ``stations/ocr/preprocessing.py`` lines 86-103.
OpenCV-only — no Pillow fallback (warpAffine has no PIL equivalent).
"""

from __future__ import annotations

import logging
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("deskew")
class DeskewOp:
    name = "deskew"
    input_keys = ("image",)
    output_keys = ("image",)

    def __init__(self, min_angle: float = 0.5, max_angle: float = 15.0):
        self._min_angle = min_angle
        self._max_angle = max_angle

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        try:
            import cv2
            import numpy as np
        except ImportError:
            logger.warning("Deskew: cv2 not available, skipping (no Pillow fallback)")
            return ctx

        img = ctx["image"]

        # Need grayscale for thresholding — work on a copy if colour
        if img.ndim == 3:
            work = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            work = img

        coords = np.column_stack(np.where(work < 128))
        if len(coords) < 500:
            logger.info("Deskew: insufficient dark pixels (%d < 500), skipping", len(coords))
            return ctx

        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        if not (self._min_angle < abs(angle) < self._max_angle):
            logger.info(
                "Deskew: angle=%.2f outside [%.1f, %.1f], skipping",
                angle, self._min_angle, self._max_angle,
            )
            return ctx

        h, w = img.shape[:2]
        center = (w // 2, h // 2)
        rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
        ctx["image"] = cv2.warpAffine(
            img,
            rot_mat,
            (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        logger.info("Deskew: rotated %.2f deg (%dx%d)", angle, w, h)
        return ctx

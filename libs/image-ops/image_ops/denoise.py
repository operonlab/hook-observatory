"""Image denoise operator.

Extracted from ``stations/ocr/preprocessing.py`` line 83.
cv2 primary (Non-local Means), Pillow fallback (double-pass sharpen).
"""

from __future__ import annotations

import logging
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("denoise")
class ImageDenoiseOp:
    name = "denoise"
    input_keys = ("image",)
    output_keys = ("image",)

    def __init__(self, h: float = 10.0):
        self._h = h

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        img = ctx["image"]

        try:
            import cv2

            if img.ndim == 2:
                ctx["image"] = cv2.fastNlMeansDenoising(img, h=self._h)
                logger.info("Denoise: cv2 fastNlMeansDenoising (gray, h=%.1f)", self._h)
            else:
                ctx["image"] = cv2.fastNlMeansDenoisingColored(img, h=self._h)
                logger.info("Denoise: cv2 fastNlMeansDenoisingColored (colour, h=%.1f)", self._h)
            return ctx
        except ImportError:
            pass

        # Pillow fallback — double-pass sharpen (matches OCR preprocessing.py lines 122-125)
        try:
            import numpy as np
            from PIL import Image, ImageFilter

            if img.ndim == 2:
                pil_img = Image.fromarray(img, mode="L")
            else:
                pil_img = Image.fromarray(img)

            sharpened = pil_img.filter(ImageFilter.SHARPEN)
            sharpened = sharpened.filter(ImageFilter.SHARPEN)
            ctx["image"] = np.array(sharpened)
            logger.info("Denoise: Pillow double-pass SHARPEN fallback")
            return ctx
        except ImportError:
            logger.warning("Denoise: neither cv2 nor Pillow available, skipping")
            return ctx

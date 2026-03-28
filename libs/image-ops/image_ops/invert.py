"""Color inversion operator — for dark-background images.

Extracted from OCR Tesseract engine dark-background handling
(stations/ocr/engines/tesseract.py lines 91-93).
"""

from __future__ import annotations

import logging
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("invert")
class InvertOp:
    """Invert image colors, optionally only when the image is dark.

    ``auto_detect=True`` checks mean pixel brightness; inverts only if < 100
    (matching the Tesseract ``_is_dark`` heuristic).
    ``auto_detect=False`` always inverts.

    Supports both Pillow Image and ndarray inputs.
    """

    name = "invert"
    input_keys = ("image",)
    output_keys = ("image",)

    def __init__(self, auto_detect: bool = False):
        if isinstance(auto_detect, (str, float)):
            self.auto_detect = bool(int(auto_detect))
        else:
            self.auto_detect = auto_detect

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        import numpy as np

        img = ctx["image"]
        is_ndarray = isinstance(img, np.ndarray)

        if is_ndarray:
            if self.auto_detect and not self._is_dark_ndarray(img):
                logger.debug("invert: auto_detect skipped (image is not dark)")
                return ctx
            ctx["image"] = np.uint8(255) - img.astype(np.uint8)
            logger.debug("invert: applied (ndarray path)")
        else:
            # Pillow path
            from PIL import ImageOps

            if self.auto_detect and not self._is_dark_pil(img):
                logger.debug("invert: auto_detect skipped (image is not dark)")
                return ctx
            ctx["image"] = ImageOps.invert(img.convert("RGB"))
            logger.debug("invert: applied (Pillow path)")

        return ctx

    @staticmethod
    def _is_dark_ndarray(img) -> bool:
        """Check mean brightness of ndarray image."""
        import numpy as np

        if img.ndim == 3:
            gray = np.mean(img, axis=2)
        else:
            gray = img
        return float(np.mean(gray)) < 100

    @staticmethod
    def _is_dark_pil(img) -> bool:
        """Check mean brightness of Pillow image."""
        try:
            gray = img.convert("L")
            pixels = list(gray.getdata())
            return (sum(pixels) / len(pixels)) < 100
        except Exception:
            return False

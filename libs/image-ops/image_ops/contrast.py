"""Contrast enhancement operator — Pillow autocontrast + contrast boost.

Extracted from OCR preprocessing Pillow fallback path
(stations/ocr/preprocessing.py lines 121, 128-129).
"""

from __future__ import annotations

import logging
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("contrast")
class ContrastOp:
    """Two-stage contrast enhancement: autocontrast then factor boost.

    Step 1: ``ImageOps.autocontrast`` stretches the histogram.
    Step 2: ``ImageEnhance.Contrast`` applies a multiplicative factor.

    Handles ndarray <-> PIL Image conversion transparently,
    respecting the ``color_space`` context key for correct channel order.
    """

    name = "contrast"
    input_keys = ("image",)
    output_keys = ("image",)

    def __init__(self, factor: float = 1.8, auto_cutoff: float = 2.0):
        self.factor = factor
        self.auto_cutoff = auto_cutoff

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        import numpy as np
        from PIL import Image, ImageEnhance, ImageOps

        img = ctx["image"]
        from_ndarray = isinstance(img, np.ndarray)

        if from_ndarray:
            color_space = ctx.get("color_space", "rgb")
            if color_space == "bgr":
                # BGR -> RGB for Pillow
                try:
                    import cv2
                    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                except ImportError:
                    rgb = img[:, :, ::-1].copy()
                pil_img = Image.fromarray(rgb)
            elif img.ndim == 2:
                pil_img = Image.fromarray(img, mode="L")
            else:
                pil_img = Image.fromarray(img)
        else:
            pil_img = img

        # Step 1: autocontrast — histogram stretch
        enhanced = ImageOps.autocontrast(pil_img, cutoff=self.auto_cutoff)

        # Step 2: contrast factor boost
        enhanced = ImageEnhance.Contrast(enhanced).enhance(self.factor)

        if from_ndarray:
            result = np.array(enhanced)
            color_space = ctx.get("color_space", "rgb")
            if color_space == "bgr" and result.ndim == 3:
                try:
                    import cv2
                    result = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)
                except ImportError:
                    result = result[:, :, ::-1].copy()
            ctx["image"] = result
        else:
            ctx["image"] = enhanced

        logger.debug(
            "contrast: factor=%.1f cutoff=%.1f",
            self.factor,
            self.auto_cutoff,
        )
        return ctx

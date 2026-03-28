"""Grayscale conversion operator.

Converts colour images to single-channel grayscale.
cv2 primary, Pillow fallback for RGB colour-space images.
"""

from __future__ import annotations

import logging
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("grayscale")
class GrayscaleOp:
    name = "grayscale"
    input_keys = ("image",)
    output_keys = ("image", "color_space")

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        import numpy as np

        img = ctx["image"]
        color_space = ctx.get("color_space", "")

        # Already grayscale — nothing to do
        if img.ndim == 2 or color_space == "gray":
            ctx["color_space"] = "gray"
            return ctx

        try:
            import cv2

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            logger.info("Grayscale: cv2 BGR->GRAY (%s)", img.shape)
        except ImportError:
            from PIL import Image

            if color_space == "rgb":
                pil_img = Image.fromarray(img)
            else:
                # Unknown colour space — best-effort via Pillow
                pil_img = Image.fromarray(img)
            gray = np.array(pil_img.convert("L"))
            logger.info("Grayscale: Pillow RGB->L (%s)", img.shape)

        ctx["image"] = gray
        ctx["color_space"] = "gray"
        return ctx

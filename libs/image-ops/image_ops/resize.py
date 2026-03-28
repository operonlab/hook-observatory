"""Resize operator — aspect-preserving or exact resize.

New operator for detection preprocessing and general image scaling.
"""

from __future__ import annotations

import logging
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("resize")
class ResizeOp:
    """Resize image with aspect ratio control.

    Three modes (checked in priority order):

    1. ``max_side``: scale so the longer side equals ``max_side``
       (common for detection model preprocessing).
    2. ``target_width`` and/or ``target_height`` with ``keep_aspect=True``:
       fit within the given dimensions preserving aspect ratio.
    3. ``target_width`` and ``target_height`` with ``keep_aspect=False``:
       stretch to exact dimensions.

    Uses cv2 with INTER_AREA (downscale) / INTER_CUBIC (upscale),
    falling back to Pillow LANCZOS if cv2 is unavailable.
    """

    name = "resize"
    input_keys = ("image", "width", "height")
    output_keys = ("image", "width", "height")

    def __init__(
        self,
        target_width: int | None = None,
        target_height: int | None = None,
        max_side: int | None = None,
        keep_aspect: bool = True,
    ):
        self.target_width = int(target_width) if target_width is not None else None
        self.target_height = int(target_height) if target_height is not None else None
        self.max_side = int(max_side) if max_side is not None else None
        self.keep_aspect = keep_aspect

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        import numpy as np

        img = ctx["image"]
        is_ndarray = isinstance(img, np.ndarray)

        if is_ndarray:
            src_h, src_w = img.shape[:2]
        else:
            src_w, src_h = img.size  # Pillow: (w, h)

        new_w, new_h = self._compute_dimensions(src_w, src_h)

        if new_w == src_w and new_h == src_h:
            logger.debug("resize: no-op (already %dx%d)", src_w, src_h)
            return ctx

        if is_ndarray:
            ctx["image"] = self._resize_cv2(img, new_w, new_h, src_w)
        else:
            ctx["image"] = self._resize_pil(img, new_w, new_h)

        ctx["width"] = new_w
        ctx["height"] = new_h
        logger.debug("resize: %dx%d -> %dx%d", src_w, src_h, new_w, new_h)
        return ctx

    def _compute_dimensions(self, src_w: int, src_h: int) -> tuple[int, int]:
        """Compute target dimensions based on configuration."""
        if self.max_side is not None:
            longer = max(src_w, src_h)
            if longer <= self.max_side:
                return src_w, src_h
            scale = self.max_side / longer
            return max(1, round(src_w * scale)), max(1, round(src_h * scale))

        tw = self.target_width
        th = self.target_height

        if tw is None and th is None:
            return src_w, src_h

        if not self.keep_aspect:
            return tw or src_w, th or src_h

        # Aspect-preserving
        if tw is not None and th is not None:
            scale = min(tw / src_w, th / src_h)
        elif tw is not None:
            scale = tw / src_w
        else:
            scale = th / src_h  # type: ignore[operator]

        return max(1, round(src_w * scale)), max(1, round(src_h * scale))

    @staticmethod
    def _resize_cv2(img, new_w: int, new_h: int, src_w: int):
        """Resize using cv2 with appropriate interpolation."""
        import cv2

        interp = cv2.INTER_AREA if new_w < src_w else cv2.INTER_CUBIC
        return cv2.resize(img, (new_w, new_h), interpolation=interp)

    @staticmethod
    def _resize_pil(img, new_w: int, new_h: int):
        """Resize using Pillow LANCZOS."""
        from PIL import Image

        return img.resize((new_w, new_h), Image.LANCZOS)

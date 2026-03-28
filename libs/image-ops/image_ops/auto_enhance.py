"""Auto-enhance operator — heuristic-driven image enhancement.

Wraps the ``needs_preprocessing()`` heuristic from
stations/ocr/preprocessing.py with dual cv2/Pillow execution paths.
"""

from __future__ import annotations

import logging
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("auto-enhance")
class AutoEnhanceOp:
    """Convenience all-in-one enhancement that detects and corrects poor images.

    Heuristic (from OCR preprocessing):
      - Convert to grayscale temporarily
      - Check ``stddev < 50`` (low contrast) OR ``mean < 80`` or ``> 220``
      - If neither condition is met and ``force=False``, return unchanged

    Enhancement paths:
      - **cv2**: grayscale -> CLAHE(3.0, 8x8) -> fastNlMeansDenoising(h=10)
      - **Pillow fallback**: autocontrast(cutoff=2) -> sharpen x2 -> contrast x1.8
    """

    name = "auto-enhance"
    input_keys = ("image",)
    output_keys = ("image",)

    def __init__(self, force: bool = False):
        self.force = bool(int(force)) if isinstance(force, (str, float)) else force

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        import numpy as np

        img = ctx["image"]
        is_ndarray = isinstance(img, np.ndarray)

        if not self.force:
            needed, reason = self._check_needed(img, is_ndarray)
            if not needed:
                logger.debug("auto-enhance: skipped (image looks fine)")
                return ctx
            logger.debug("auto-enhance: triggered (%s)", reason)
        else:
            logger.debug("auto-enhance: forced")

        # Try cv2 path first
        if is_ndarray:
            try:
                ctx["image"] = self._enhance_cv2(img)
                logger.debug("auto-enhance: cv2 path applied")
                return ctx
            except ImportError:
                pass

        # Pillow fallback (works for both ndarray and PIL Image)
        ctx["image"] = self._enhance_pillow(img, is_ndarray)
        logger.debug("auto-enhance: Pillow fallback applied")
        return ctx

    @staticmethod
    def _check_needed(img, is_ndarray: bool) -> tuple[bool, str]:
        """Heuristic check matching OCR preprocessing.py logic."""
        import numpy as np

        if is_ndarray:
            if img.ndim == 3:
                gray = np.mean(img, axis=2)
            else:
                gray = img.astype(np.float64)
            mean_val = float(np.mean(gray))
            std_val = float(np.std(gray))
        else:
            # Pillow Image
            from PIL import ImageStat

            gray = img.convert("L")
            stat = ImageStat.Stat(gray)
            mean_val = stat.mean[0]
            std_val = stat.stddev[0]

        if std_val < 50:
            return True, f"low contrast (stddev={std_val:.1f})"
        if mean_val < 80:
            return True, f"too dark (mean={mean_val:.1f})"
        if mean_val > 220:
            return True, f"too bright (mean={mean_val:.1f})"
        return False, ""

    @staticmethod
    def _enhance_cv2(img):
        """CLAHE + denoise via OpenCV."""
        import cv2

        if img.ndim == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        denoised = cv2.fastNlMeansDenoising(enhanced, h=10)

        # If input was color, merge back to 3-channel
        if img.ndim == 3:
            # Replace luminance in original — convert to LAB, replace L, convert back
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            lab[:, :, 0] = denoised
            return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        return denoised

    @staticmethod
    def _enhance_pillow(img, is_ndarray: bool):
        """Autocontrast + sharpen + contrast boost via Pillow."""
        import numpy as np
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps

        if is_ndarray:
            if img.ndim == 2:
                pil_img = Image.fromarray(img, mode="L")
            else:
                pil_img = Image.fromarray(img)
        else:
            pil_img = img

        # Step 1: autocontrast
        enhanced = ImageOps.autocontrast(pil_img, cutoff=2)

        # Step 2: double sharpen (for handwriting / degraded text)
        sharpened = enhanced.filter(ImageFilter.SHARPEN)
        sharpened = sharpened.filter(ImageFilter.SHARPEN)

        # Step 3: contrast boost
        result = ImageEnhance.Contrast(sharpened).enhance(1.8)

        if is_ndarray:
            return np.array(result)
        return result

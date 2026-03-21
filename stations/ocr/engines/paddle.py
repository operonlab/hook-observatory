"""PaddleOCR engine — PP-OCRv5 with native Chinese support.

Best open-source engine for Chinese text (printed + handwritten).
PP-OCRv5 handwriting accuracy improved +13% over v4.
Supports 100+ languages, CPU-friendly, Apache-2.0 license.

Requires: pip install paddlepaddle paddleocr
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import register

logger = logging.getLogger(__name__)

# Lazy singleton — initialized on first use to avoid slow startup
_ocr_instances: dict[str, object] = {}


def _get_ocr(lang: str = "ch"):
    """Get or create a PaddleOCR instance (cached per language)."""
    if lang not in _ocr_instances:
        import os

        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import PaddleOCR

        _ocr_instances[lang] = PaddleOCR(lang=lang)
    return _ocr_instances[lang]


# Language code mapping: OCR station codes → PaddleOCR codes
_LANG_MAP = {
    "zh-Hant": "ch",  # PaddleOCR uses 'ch' for both simplified + traditional
    "zh-Hans": "ch",
    "en": "en",
    "ja": "japan",
    "ko": "korean",
    "fr": "fr",
    "de": "german",
    "es": "es",
    "pt": "pt",
    "ru": "ru",
    "ar": "ar",
    "vi": "vi",
}


def _map_lang(codes: list[str] | None) -> str:
    """Map station language codes to PaddleOCR language code.

    PaddleOCR uses a single language per instance. For zh+en mixed,
    'ch' handles both well.
    """
    if not codes:
        return "ch"
    for code in codes:
        mapped = _LANG_MAP.get(code)
        if mapped:
            return mapped
    return "ch"


@register("paddle")
class PaddleOCREngine:
    """PaddleOCR PP-OCRv5 engine — best for Chinese printed + handwritten text."""

    name = "paddle"

    def extract(self, file_path: str, languages: list[str] | None = None) -> dict:
        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "paddle"}

        try:
            from paddleocr import PaddleOCR  # noqa: F401
        except ImportError:
            return {
                "error": "paddleocr not installed. Run: pip install paddlepaddle paddleocr",
                "engine": "paddle",
            }

        lang = _map_lang(languages)

        try:
            ocr = _get_ocr(lang)
            result = ocr.ocr(str(path))
        except Exception as e:
            return {"error": f"PaddleOCR failed: {e}", "engine": "paddle"}

        blocks = []
        all_text = []

        if result:
            for page in result:
                # PP-OCRv5 returns OCRResult objects with .json['res']
                res = page.json["res"] if hasattr(page, "json") else None
                if res and "rec_texts" in res:
                    texts = res["rec_texts"]
                    scores = res["rec_scores"]
                    polys = res.get("dt_polys", [])
                    for i, (text, score) in enumerate(zip(texts, scores, strict=False)):
                        if not text.strip():
                            continue
                        block = {
                            "text": text.strip(),
                            "confidence": round(float(score), 4),
                        }
                        if i < len(polys) and polys[i] is not None:
                            poly = polys[i]
                            try:
                                xs = [p[0] for p in poly]
                                ys = [p[1] for p in poly]
                                block.update(
                                    {
                                        "x": float(min(xs)),
                                        "y": float(min(ys)),
                                        "width": float(max(xs) - min(xs)),
                                        "height": float(max(ys) - min(ys)),
                                    }
                                )
                            except (TypeError, IndexError):
                                pass
                        blocks.append(block)
                        all_text.append(text.strip())

        # Sort blocks by position (top-to-bottom, left-to-right)
        blocks.sort(key=lambda b: (b.get("y", 0), b.get("x", 0)))

        return {
            "text": "\n".join(all_text) if all_text else "",
            "blocks": blocks,
            "languages": languages or ["zh-Hant", "en"],
            "engine": "paddle",
        }

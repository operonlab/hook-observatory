"""Tesseract OCR engine — pytesseract + Pillow with multi-pass strategy.

Supports PSM mode selection, dark background inversion, and word-level
bounding boxes. Requires: brew install tesseract tesseract-lang
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import register

# Language code mapping: OCR station codes → Tesseract codes
_LANG_MAP = {
    "zh-Hant": "chi_tra",
    "zh-Hans": "chi_sim",
    "en": "eng",
    "ja": "jpn",
    "ko": "kor",
    "fr": "fra",
    "de": "deu",
    "es": "spa",
    "pt": "por",
    "ru": "rus",
    "ar": "ara",
    "vi": "vie",
    "th": "tha",
}


def _map_lang(code: str) -> str:
    """Map station language code to Tesseract language code."""
    return _LANG_MAP.get(code, code)


@register("tesseract")
class TesseractOCREngine:
    """Tesseract OCR with multi-pass strategy and PSM control."""

    name = "tesseract"

    def extract(
        self,
        file_path: str,
        languages: list[str] | None = None,
        *,
        psm: int = 3,
        invert: bool = False,
    ) -> dict:
        """Extract text from image using Tesseract.

        Args:
            file_path: Path to image file.
            languages: Language codes (mapped to Tesseract codes).
            psm: Page segmentation mode (3=auto, 6=block, 7=line, 11=sparse).
            invert: Invert colors before OCR (for dark backgrounds).
        """
        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "tesseract"}

        ext = path.suffix.lower()
        if ext == ".pdf":
            return self._extract_pdf(file_path, languages, psm=psm)

        try:
            import pytesseract
            from PIL import Image, ImageOps
        except ImportError:
            return {
                "error": "pytesseract or Pillow not installed. Run: pip install pytesseract Pillow",
                "engine": "tesseract",
            }

        lang_str = "+".join(_map_lang(l) for l in (languages or ["en"]))
        config = f"--psm {psm}"

        try:
            img = Image.open(file_path)
        except Exception as e:
            return {"error": f"Cannot open image: {e}", "engine": "tesseract"}

        blocks = []

        # Pass 1: Standard OCR
        blocks.extend(self._ocr_pass(img, lang_str, config, "standard"))

        # Pass 2: Inverted (for dark backgrounds) — if requested or auto
        if invert or self._is_dark(img):
            try:
                img_inv = ImageOps.invert(img.convert("RGB"))
                blocks.extend(self._ocr_pass(img_inv, lang_str, config, "inverted"))
            except Exception:
                pass

        # Deduplicate by text proximity
        blocks = self._deduplicate(blocks)

        full_text = "\n".join(b["text"] for b in blocks if b.get("text"))
        return {
            "text": full_text,
            "blocks": blocks,
            "languages": languages or ["en"],
            "engine": "tesseract",
            "psm": psm,
        }

    def _ocr_pass(self, img, lang_str: str, config: str, pass_name: str) -> list[dict]:
        """Run a single OCR pass and return block-level results."""
        import pytesseract

        try:
            data = pytesseract.image_to_data(
                img, lang=lang_str, config=config, output_type=pytesseract.Output.DICT
            )
        except Exception as e:
            return [{"error": str(e), "pass": pass_name}]

        w, h = img.size
        blocks = []
        n = len(data["text"])
        for i in range(n):
            text = data["text"][i].strip()
            conf = int(data["conf"][i]) if data["conf"][i] != "-1" else -1
            if text and conf > 20:
                blocks.append(
                    {
                        "text": text,
                        "confidence": conf / 100.0,
                        "x": data["left"][i] / w if w else 0,
                        "y": data["top"][i] / h if h else 0,
                        "width": data["width"][i] / w if w else 0,
                        "height": data["height"][i] / h if h else 0,
                        "pass": pass_name,
                    }
                )
        return blocks

    def _extract_pdf(self, file_path: str, languages: list[str] | None, *, psm: int = 3) -> dict:
        """Extract text from PDF using Tesseract (converts pages to images first)."""
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            return {
                "error": "pytesseract or Pillow not installed",
                "engine": "tesseract",
            }

        # Use pdftoppm if available, otherwise fall back to simple text extraction
        lang_str = "+".join(_map_lang(l) for l in (languages or ["en"]))
        config = f"--psm {psm}"

        try:
            # Try pdf2image if available
            from pdf2image import convert_from_path

            images = convert_from_path(file_path, dpi=200)
        except ImportError:
            # Fallback: use tesseract directly on PDF (requires tesseract PDF support)
            try:
                result = subprocess.run(
                    ["tesseract", file_path, "stdout", "-l", lang_str, config],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                return {
                    "text": result.stdout.strip(),
                    "blocks": [],
                    "languages": languages or ["en"],
                    "engine": "tesseract",
                }
            except Exception as e:
                return {"error": f"PDF extraction failed: {e}", "engine": "tesseract"}

        all_blocks = []
        for i, img in enumerate(images):
            page_blocks = self._ocr_pass(img, lang_str, config, f"page-{i + 1}")
            for b in page_blocks:
                b["page"] = i + 1
            all_blocks.extend(page_blocks)

        full_text = "\n".join(b["text"] for b in all_blocks if b.get("text"))
        return {
            "text": full_text,
            "blocks": all_blocks,
            "languages": languages or ["en"],
            "engine": "tesseract",
        }

    @staticmethod
    def _is_dark(img) -> bool:
        """Heuristic: check if image has a dark background."""
        try:
            gray = img.convert("L")
            pixels = list(gray.getdata())
            avg = sum(pixels) / len(pixels)
            return avg < 100
        except Exception:
            return False

    @staticmethod
    def _deduplicate(blocks: list[dict], threshold: float = 0.02) -> list[dict]:
        """Remove duplicate blocks with similar positions."""
        seen = []
        result = []
        for b in blocks:
            if "error" in b:
                continue
            key = (b.get("text", ""), round(b.get("x", 0), 2), round(b.get("y", 0), 2))
            if key not in seen:
                seen.append(key)
                result.append(b)
        return result

"""Gemini Flash Vision API engine — cheap cloud OCR fallback.

Best for: bulk image OCR where cost matters, general-purpose text extraction.
Requires: GEMINI_API_KEY environment variable.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from . import register


def _retry_with_backoff(fn, max_retries=3, base_delay=1.0, max_delay=30.0):
    """Retry with exponential backoff."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                time.sleep(delay)
    raise last_exc

_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-2.5-flash:generateContent"
)


@register("gemini")
class GeminiOCREngine:
    """Gemini Flash Vision API for cost-effective cloud OCR."""

    name = "gemini"

    def extract(self, file_path: str, languages: list[str] | None = None) -> dict:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return {
                "error": "GEMINI_API_KEY not set. Export it or add to .env",
                "engine": "gemini",
            }

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "gemini"}

        ext = path.suffix.lower()

        if ext == ".pdf":
            return self._extract_pdf(path, languages, api_key)

        mime = _MIME_MAP.get(ext)
        if not mime:
            return {
                "error": f"Unsupported format: {ext}. Supported: {list(_MIME_MAP.keys())}",
                "engine": "gemini",
            }

        image_data = base64.b64encode(path.read_bytes()).decode("utf-8")

        lang_hint = ", ".join(languages) if languages else "auto-detect"
        prompt = (
            f"Extract ALL text from this image. Languages present: {lang_hint}.\n"
            "Return a JSON object with:\n"
            '- "text": the full extracted text\n'
            '- "blocks": array of {{"text": str, "type": "paragraph"|"heading"|"list"|"table"|"handwritten"}}\n'
            "Be thorough — include every piece of visible text. Preserve original formatting and line breaks."
        )

        return self._call_api(api_key, prompt, image_data, mime, languages)

    def _extract_pdf(self, path: Path, languages: list[str] | None, api_key: str) -> dict:
        """Convert PDF to image via qlmanage, then extract."""
        try:
            import subprocess
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                subprocess.run(
                    ["qlmanage", "-t", "-s", "2000", "-o", tmpdir, str(path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                png_files = list(Path(tmpdir).glob("*.png"))
                if not png_files:
                    return {
                        "error": "Failed to convert PDF to image for Gemini API",
                        "engine": "gemini",
                    }

                img_path = png_files[0]
                image_data = base64.b64encode(img_path.read_bytes()).decode("utf-8")

                lang_hint = ", ".join(languages) if languages else "auto-detect"
                prompt = (
                    f"Extract ALL text from this PDF page image. Languages: {lang_hint}.\n"
                    "Return a JSON object with:\n"
                    '- "text": the full extracted text\n'
                    '- "blocks": array of {{"text": str, "type": "paragraph"|"heading"|"list"|"table"|"handwritten"}}\n'
                    "Be thorough. Preserve formatting."
                )

                result = self._call_api(api_key, prompt, image_data, "image/png", languages)
                if "blocks" in result:
                    for b in result["blocks"]:
                        b["page"] = 1
                return result

        except Exception as e:
            return {"error": f"PDF processing failed: {e}", "engine": "gemini"}

    def _call_api(
        self,
        api_key: str,
        prompt: str,
        image_data: str,
        mime: str,
        languages: list[str] | None,
    ) -> dict:
        """Call Gemini API with inline image data."""
        import httpx

        body = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": image_data,
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 4096,
            },
        }

        try:
            resp = httpx.post(
                _API_URL,
                headers={
                    "x-goog-api-key": api_key,
                    "content-type": "application/json",
                },
                json=body,
                timeout=60,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return {
                "error": f"Gemini API error ({e.response.status_code}): {e.response.text[:300]}",
                "engine": "gemini",
            }
        except Exception as e:
            return {"error": f"Gemini API request failed: {e}", "engine": "gemini"}

        data = resp.json()

        # Extract text from Gemini response structure
        content_text = ""
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part:
                    content_text += part["text"]

        parsed = self._parse_response(content_text)

        usage_meta = data.get("usageMetadata", {})
        return {
            "text": parsed.get("text", content_text),
            "blocks": parsed.get("blocks", []),
            "languages": languages or ["auto"],
            "engine": "gemini",
            "model": "gemini-2.5-flash",
            "usage": {
                "input_tokens": usage_meta.get("promptTokenCount", 0),
                "output_tokens": usage_meta.get("candidatesTokenCount", 0),
            },
        }

    @staticmethod
    def _parse_response(text: str) -> dict:
        """Try to parse JSON from Gemini's response."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        if "```" in text:
            for block in text.split("```"):
                block = block.strip()
                if block.startswith("json"):
                    block = block[4:].strip()
                try:
                    return json.loads(block)
                except json.JSONDecodeError:
                    continue

        return {"text": text, "blocks": []}

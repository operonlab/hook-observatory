"""Claude Vision API engine — uses Claude's vision capability for OCR.

Best for: handwritten text, complex layouts, tables, charts, mixed media.
Requires: ANTHROPIC_API_KEY environment variable.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from . import register

# Supported image MIME types for Claude Vision
_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Max image size for Claude API (20MB)
_MAX_SIZE = 20 * 1024 * 1024


@register("claude")
class ClaudeOCREngine:
    """Claude Vision API for high-accuracy OCR on complex images."""

    name = "claude"

    def extract(self, file_path: str, languages: list[str] | None = None) -> dict:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return {
                "error": "ANTHROPIC_API_KEY not set. Export it or add to .env",
                "engine": "claude",
            }

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "claude"}

        ext = path.suffix.lower()

        # PDF: convert pages to images first
        if ext == ".pdf":
            return self._extract_pdf(path, languages, api_key)

        mime = _MIME_MAP.get(ext)
        if not mime:
            return {
                "error": f"Unsupported format: {ext}. Supported: {list(_MIME_MAP.keys())}",
                "engine": "claude",
            }

        if path.stat().st_size > _MAX_SIZE:
            return {"error": f"File too large (>{_MAX_SIZE // 1024 // 1024}MB)", "engine": "claude"}

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
        """Convert PDF pages to images and extract text from each."""
        try:
            # Use sips (macOS native) to convert PDF to PNG per page
            # Fallback: use first page only for simplicity
            import subprocess

            # macOS: use qlmanage for quick PDF→PNG conversion
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                result = subprocess.run(
                    ["qlmanage", "-t", "-s", "2000", "-o", tmpdir, str(path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                # qlmanage creates a .png file
                png_files = list(Path(tmpdir).glob("*.png"))
                if not png_files:
                    return {
                        "error": "Failed to convert PDF to image for Claude API",
                        "engine": "claude",
                    }

                # Use the first rendered page
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
            return {"error": f"PDF processing failed: {e}", "engine": "claude"}

    def _call_api(
        self,
        api_key: str,
        prompt: str,
        image_data: str,
        mime: str,
        languages: list[str] | None,
    ) -> dict:
        """Call Claude API with vision content."""
        import httpx

        body = {
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime,
                                "data": image_data,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }

        try:
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=body,
                timeout=60,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return {
                "error": f"Claude API error ({e.response.status_code}): {e.response.text[:300]}",
                "engine": "claude",
            }
        except Exception as e:
            return {"error": f"Claude API request failed: {e}", "engine": "claude"}

        data = resp.json()
        content_text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content_text += block["text"]

        # Try to parse JSON from response
        parsed = self._parse_response(content_text)

        return {
            "text": parsed.get("text", content_text),
            "blocks": parsed.get("blocks", []),
            "languages": languages or ["auto"],
            "engine": "claude",
            "model": "claude-haiku-4-5-20251001",
            "usage": {
                "input_tokens": data.get("usage", {}).get("input_tokens", 0),
                "output_tokens": data.get("usage", {}).get("output_tokens", 0),
            },
        }

    @staticmethod
    def _parse_response(text: str) -> dict:
        """Try to parse JSON from Claude's response."""
        # Try direct JSON parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code block
        if "```" in text:
            for block in text.split("```"):
                block = block.strip()
                if block.startswith("json"):
                    block = block[4:].strip()
                try:
                    return json.loads(block)
                except json.JSONDecodeError:
                    continue

        # Fallback: return raw text
        return {"text": text, "blocks": []}

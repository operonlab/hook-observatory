"""Gemini Vision API engine — bulk visual analysis at low cost.

Best for: batch image processing, general descriptions.
Requires: GEMINI_API_KEY environment variable.
"""

from __future__ import annotations

import base64
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
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
)

_TASK_PROMPTS = {
    "describe": "Describe this image in detail. Include all visible elements, text, and composition.",
    "classify": 'Classify this image. Return a JSON object: {"category": str, "confidence": float, "tags": [str]}',
    "qa": None,
}


@register("gemini")
class GeminiVisionEngine:
    """Gemini Flash Vision — bulk analysis at low cost."""

    name = "gemini"

    _SUPPORTED_TASKS = {"describe", "classify", "qa"}

    def analyze(self, file_path: str, task: str = "describe", prompt: str | None = None) -> dict:
        if task not in self._SUPPORTED_TASKS:
            return {
                "error": f"Gemini engine doesn't support task '{task}'. Supported: {self._SUPPORTED_TASKS}",
                "engine": "gemini",
                "task": task,
            }

        if task == "qa" and not prompt:
            return {"error": "task='qa' requires a prompt", "engine": "gemini", "task": task}

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return {"error": "GEMINI_API_KEY not set", "engine": "gemini", "task": task}

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "gemini", "task": task}

        ext = path.suffix.lower()
        mime = _MIME_MAP.get(ext)
        if not mime:
            return {"error": f"Unsupported format: {ext}", "engine": "gemini", "task": task}

        image_data = base64.b64encode(path.read_bytes()).decode("utf-8")
        prompt_text = prompt if task == "qa" else _TASK_PROMPTS.get(task, "Describe this image.")

        try:
            import httpx

            def _call_api():
                r = httpx.post(
                    _API_URL,
                    headers={
                        "x-goog-api-key": api_key,
                        "content-type": "application/json",
                    },
                    json={
                        "contents": [
                            {
                                "parts": [
                                    {"inline_data": {"mime_type": mime, "data": image_data}},
                                    {"text": prompt_text},
                                ],
                            }
                        ],
                        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
                    },
                    timeout=60,
                )
                if r.status_code >= 500:
                    r.raise_for_status()
                return r

            resp = _retry_with_backoff(_call_api, max_retries=3, base_delay=1.0, max_delay=30.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return {
                "error": f"Gemini API error ({e.response.status_code}): {e.response.text[:300]}",
                "engine": "gemini",
                "task": task,
            }
        except Exception as e:
            return {"error": f"Gemini API failed: {e}", "engine": "gemini", "task": task}

        data = resp.json()
        text = ""
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part:
                    text += part["text"]

        usage_meta = data.get("usageMetadata", {})
        return {
            "result": text.strip(),
            "engine": "gemini",
            "task": task,
            "model": "gemini-2.5-flash",
            "usage": {
                "input_tokens": usage_meta.get("promptTokenCount", 0),
                "output_tokens": usage_meta.get("candidatesTokenCount", 0),
            },
        }

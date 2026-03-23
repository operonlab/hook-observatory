"""Claude Vision API engine — complex visual reasoning.

Best for: complex charts, dense documents, multi-step reasoning.
Uses Anthropic API with base64 image input.
Requires: ANTHROPIC_API_KEY environment variable.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from . import register

_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_TASK_PROMPTS = {
    "describe": "Describe this image in detail. Include all visible elements, text, colors, and composition.",
    "classify": "Classify this image. What is the main subject? Provide a concise category and confidence level.",
    "qa": None,
}


@register("claude")
class ClaudeVisionEngine:
    """Claude Vision API — complex visual reasoning."""

    name = "claude"

    _SUPPORTED_TASKS = {"describe", "classify", "qa"}

    def analyze(self, file_path: str, task: str = "describe", prompt: str | None = None) -> dict:
        if task not in self._SUPPORTED_TASKS:
            return {
                "error": f"Claude engine doesn't support task '{task}'. Supported: {self._SUPPORTED_TASKS}",
                "engine": "claude",
                "task": task,
            }

        if task == "qa" and not prompt:
            return {"error": "task='qa' requires a prompt", "engine": "claude", "task": task}

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return {"error": "ANTHROPIC_API_KEY not set", "engine": "claude", "task": task}

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "claude", "task": task}

        ext = path.suffix.lower()
        mime = _MIME_MAP.get(ext)
        if not mime:
            return {"error": f"Unsupported format: {ext}", "engine": "claude", "task": task}

        image_data = base64.b64encode(path.read_bytes()).decode("utf-8")
        prompt_text = prompt if task == "qa" else _TASK_PROMPTS.get(task, "Describe this image.")

        try:
            import httpx

            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1024,
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
                                {"type": "text", "text": prompt_text},
                            ],
                        }
                    ],
                },
                timeout=60,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return {
                "error": f"Claude API error ({e.response.status_code}): {e.response.text[:300]}",
                "engine": "claude",
                "task": task,
            }
        except Exception as e:
            return {"error": f"Claude API failed: {e}", "engine": "claude", "task": task}

        data = resp.json()
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")

        usage = data.get("usage", {})
        return {
            "result": text.strip(),
            "engine": "claude",
            "task": task,
            "model": "claude-haiku-4-5-20251001",
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
        }

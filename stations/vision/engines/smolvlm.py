"""SmolVLM2-500M engine — lightweight vision-language model.

500M params, ~1.2GB memory, MLX native. Best for quick image descriptions,
visual Q&A, and classification. English-focused.

Requires: pip install mlx-vlm
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from . import register

logger = logging.getLogger(__name__)

_last_used: float = 0.0
MODEL_IDLE_TTL = 300
_model = None
_processor = None
MODEL_ID = "mlx-community/SmolVLM2-500M-Instruct-4bit"

_TASK_PROMPTS = {
    "describe": "Describe this image in detail.",
    "classify": "Classify this image. What is the main subject? Provide a concise category.",
    "qa": None,  # Uses user prompt
}


def _mark_used():
    global _last_used
    _last_used = time.monotonic()


def unload_model() -> bool:
    """Unload SmolVLM model and free memory. Returns True if unloaded."""
    import gc

    global _model, _processor
    if _model is None:
        return False
    _model = None
    _processor = None
    gc.collect()
    logger.info("Unloaded SmolVLM model, memory freed")
    return True


def is_idle() -> bool:
    """Check if model is loaded but idle beyond TTL."""
    if _model is None:
        return False
    return (time.monotonic() - _last_used) > MODEL_IDLE_TTL


def _load():
    global _model, _processor
    if _model is not None:
        return
    from mlx_vlm import load

    logger.info("Loading SmolVLM2 model (%s)...", MODEL_ID)
    _model, _processor = load(MODEL_ID)
    logger.info("SmolVLM2 model loaded")


@register("smolvlm")
class SmolVLMEngine:
    """SmolVLM2-500M — lightweight VLM for describe/qa/classify."""

    name = "smolvlm"

    _SUPPORTED_TASKS = {"describe", "classify", "qa"}

    def analyze(self, file_path: str, task: str = "describe", prompt: str | None = None) -> dict:
        if task not in self._SUPPORTED_TASKS:
            return {
                "error": f"SmolVLM doesn't support task '{task}'. Supported: {self._SUPPORTED_TASKS}",
                "engine": "smolvlm",
                "task": task,
            }

        if task == "qa" and not prompt:
            return {"error": "task='qa' requires a prompt", "engine": "smolvlm", "task": task}

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "smolvlm", "task": task}

        try:
            from mlx_vlm import load  # noqa: F401
        except ImportError:
            return {
                "error": "mlx-vlm not installed. Run: pip install mlx-vlm",
                "engine": "smolvlm",
                "task": task,
            }

        _mark_used()
        _load()

        try:
            from mlx_vlm import generate

            prompt_text = (
                prompt if task == "qa" else _TASK_PROMPTS.get(task, "Describe this image.")
            )

            output = generate(
                _model,
                _processor,
                str(path),
                prompt_text,
                max_tokens=512,
            )

            return {
                "result": output.strip(),
                "engine": "smolvlm",
                "task": task,
                "model": MODEL_ID,
            }
        except Exception as e:
            return {"error": f"SmolVLM analysis failed: {e}", "engine": "smolvlm", "task": task}

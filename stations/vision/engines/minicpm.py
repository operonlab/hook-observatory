"""MiniCPM-V 2.6 engine — heavy VLM with Chinese/Japanese support.

8B params, ~5GB memory. Best for dense image descriptions in Chinese,
OCR-like tasks, and complex visual Q&A.

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
MODEL_ID = "mlx-community/MiniCPM-V-2_6-8bit"

_TASK_PROMPTS = {
    "describe": "請詳細描述這張圖片的內容。",
    "classify": "請分類這張圖片，指出主要主題。",
    "qa": None,
}


def _mark_used():
    global _last_used
    _last_used = time.monotonic()


def unload_model() -> bool:
    """Unload MiniCPM-V model and free memory. Returns True if unloaded."""
    import gc

    global _model, _processor
    if _model is None:
        return False
    _model = None
    _processor = None
    gc.collect()
    logger.info("Unloaded MiniCPM-V model, memory freed")
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

    logger.info("Loading MiniCPM-V model (%s)...", MODEL_ID)
    _model, _processor = load(MODEL_ID)
    logger.info("MiniCPM-V model loaded")


@register("minicpm")
class MiniCPMEngine:
    """MiniCPM-V 2.6 — heavy VLM, Chinese/Japanese/English."""

    name = "minicpm"

    _SUPPORTED_TASKS = {"describe", "classify", "qa"}

    def analyze(self, file_path: str, task: str = "describe", prompt: str | None = None) -> dict:
        if task not in self._SUPPORTED_TASKS:
            return {
                "error": f"MiniCPM doesn't support task '{task}'. Supported: {self._SUPPORTED_TASKS}",
                "engine": "minicpm",
                "task": task,
            }

        if task == "qa" and not prompt:
            return {"error": "task='qa' requires a prompt", "engine": "minicpm", "task": task}

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "minicpm", "task": task}

        try:
            from mlx_vlm import load  # noqa: F401
        except ImportError:
            return {
                "error": "mlx-vlm not installed. Run: pip install mlx-vlm",
                "engine": "minicpm",
                "task": task,
            }

        _mark_used()
        _load()

        try:
            from mlx_vlm import generate

            prompt_text = prompt if task == "qa" else _TASK_PROMPTS.get(task, "請描述這張圖片。")

            output = generate(
                _model,
                _processor,
                str(path),
                prompt_text,
                max_tokens=1024,
            )

            return {
                "result": output.strip(),
                "engine": "minicpm",
                "task": task,
                "model": MODEL_ID,
            }
        except Exception as e:
            return {"error": f"MiniCPM-V analysis failed: {e}", "engine": "minicpm", "task": task}

"""Apple Vision framework engine — macOS native visual analysis.

Free, instant, zero-dependency. Supports face detection, barcode/QR reading,
and image classification via compiled Swift binary.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from . import register

BINARY = Path(__file__).parent.parent / "bin" / "apple-vision"


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


@register("apple")
class AppleVisionEngine:
    """macOS native vision via Vision.framework."""

    name = "apple"

    _SUPPORTED_TASKS = {"face", "barcode", "classify", "detect"}

    def analyze(self, file_path: str, task: str = "classify", prompt: str | None = None) -> dict:
        if task not in self._SUPPORTED_TASKS:
            return {
                "error": f"Apple engine doesn't support task '{task}'. Supported: {self._SUPPORTED_TASKS}",
                "engine": "apple",
                "task": task,
            }

        if not BINARY.exists():
            return {
                "error": f"apple-vision binary not found at {BINARY}. Run: cd stations/vision/bin && ./build.sh",
                "engine": "apple",
                "task": task,
            }

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "apple", "task": task}

        def _run():
            return subprocess.run(
                [str(BINARY), str(path), "--task", task],
                capture_output=True,
                text=True,
                timeout=30,
            )

        try:
            result = _retry_with_backoff(_run, max_retries=3, base_delay=1.0, max_delay=30.0)
        except (subprocess.TimeoutExpired, OSError) as e:
            return {
                "error": f"apple-vision failed after retries: {e}",
                "engine": "apple",
                "task": task,
            }

        if result.returncode != 0:
            return {
                "error": f"apple-vision failed: {result.stderr.strip()}",
                "engine": "apple",
                "task": task,
            }

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {
                "error": f"Invalid JSON: {result.stdout[:200]}",
                "engine": "apple",
                "task": task,
            }

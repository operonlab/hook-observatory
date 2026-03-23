"""Apple Vision framework engine — macOS native visual analysis.

Free, instant, zero-dependency. Supports face detection, barcode/QR reading,
and image classification via compiled Swift binary.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import register

BINARY = Path(__file__).parent.parent / "bin" / "apple-vision"


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

        result = subprocess.run(
            [str(BINARY), str(path), "--task", task],
            capture_output=True,
            text=True,
            timeout=30,
        )

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

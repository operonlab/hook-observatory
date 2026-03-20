"""Apple SFSpeechRecognizer engine -- subprocess wrapper around apple-stt binary."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import register

BINARY = Path(__file__).parent.parent / "bin" / "apple-stt"


@register("apple")
class AppleSTTEngine:
    """macOS native speech recognition via SFSpeechRecognizer."""

    name = "apple"

    def transcribe(self, file_path: str, language: str = "zh-TW") -> dict:
        if not BINARY.exists():
            raise FileNotFoundError(
                f"apple-stt binary not found at {BINARY}. Run: cd stations/stt/bin && ./build.sh"
            )

        result = subprocess.run(
            [str(BINARY), file_path, "--language", language],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            return {"error": f"apple-stt failed: {result.stderr.strip()}", "engine": "apple"}

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON output: {result.stdout[:200]}", "engine": "apple"}

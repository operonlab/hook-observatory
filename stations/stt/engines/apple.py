"""Apple SFSpeechRecognizer engine -- subprocess wrapper around apple-stt binary."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from . import register

BINARY = Path(__file__).parent.parent / "bin" / "apple-stt"


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
class AppleSTTEngine:
    """macOS native speech recognition via SFSpeechRecognizer."""

    name = "apple"

    def transcribe(self, file_path: str, language: str = "zh-TW") -> dict:
        if not BINARY.exists():
            raise FileNotFoundError(
                f"apple-stt binary not found at {BINARY}. Run: cd stations/stt/bin && ./build.sh"
            )

        def _run():
            return subprocess.run(
                [str(BINARY), file_path, "--language", language],
                capture_output=True,
                text=True,
                timeout=120,
            )

        try:
            result = _retry_with_backoff(
                _run,
                max_retries=3,
                base_delay=1.0,
                max_delay=30.0,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            return {"error": f"apple-stt failed after retries: {e}", "engine": "apple"}

        if result.returncode != 0:
            return {"error": f"apple-stt failed: {result.stderr.strip()}", "engine": "apple"}

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON output: {result.stdout[:200]}", "engine": "apple"}

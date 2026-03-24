"""Apple Vision framework engine — subprocess wrapper around apple-ocr binary."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from . import register

BINARY = Path(__file__).parent.parent / "bin" / "apple-ocr"


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
class AppleOCREngine:
    """macOS native OCR via Vision framework."""

    name = "apple"

    def extract(self, file_path: str, languages: list[str] | None = None) -> dict:
        if not BINARY.exists():
            raise FileNotFoundError(
                f"apple-ocr binary not found at {BINARY}. Run: cd stations/ocr/bin && ./build.sh"
            )

        cmd = [str(BINARY), file_path]
        if languages:
            cmd.extend(["--languages", ",".join(languages)])

        def _run():
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

        try:
            result = _retry_with_backoff(_run, max_retries=3, base_delay=1.0, max_delay=30.0)
        except (subprocess.TimeoutExpired, OSError) as e:
            return {"error": f"apple-ocr failed after retries: {e}", "engine": "apple"}

        if result.returncode != 0:
            return {"error": f"apple-ocr failed: {result.stderr.strip()}", "engine": "apple"}

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON output: {result.stdout[:200]}", "engine": "apple"}

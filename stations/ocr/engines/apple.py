"""Apple Vision framework engine — subprocess wrapper around apple-ocr binary."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import register

BINARY = Path(__file__).parent.parent / "bin" / "apple-ocr"


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

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            return {"error": f"apple-ocr failed: {result.stderr.strip()}", "engine": "apple"}

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON output: {result.stdout[:200]}", "engine": "apple"}

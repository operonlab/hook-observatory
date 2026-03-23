"""Apple AVSpeechSynthesizer engine — macOS native TTS.

Free, instant, zero-dependency baseline. Quality is basic but functional.
Uses compiled Swift binary that wraps AVSpeechSynthesizer.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import register

BINARY = Path(__file__).parent.parent / "bin" / "apple-tts"


@register("apple")
class AppleTTSEngine:
    """macOS native text-to-speech via AVSpeechSynthesizer."""

    name = "apple"

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        output_path: str | None = None,
    ) -> dict:
        if not BINARY.exists():
            return {
                "error": f"apple-tts binary not found at {BINARY}. Run: cd stations/tts/bin && ./build.sh",
                "engine": "apple",
            }

        cmd = [str(BINARY), text, "--speed", str(speed)]
        if voice != "default":
            cmd.extend(["--voice", voice])
        if output_path:
            cmd.extend(["--output", output_path])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            return {"error": f"apple-tts failed: {result.stderr.strip()}", "engine": "apple"}

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON output: {result.stdout[:200]}", "engine": "apple"}

    def list_voices(self) -> list[dict]:
        if not BINARY.exists():
            return []
        result = subprocess.run(
            [str(BINARY), "--list-voices"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

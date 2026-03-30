"""IndexTTS engine — zero-shot TTS with best Chinese WER (Bilibili).

Uses subprocess bridge to IndexTTS's own venv at ~/workshop/lab/indextts/.
Requires: git clone https://github.com/index-tts/index-tts ~/workshop/lab/indextts
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile

from . import register

logger = logging.getLogger(__name__)

INDEXTTS_DIR = os.path.expanduser("~/workshop/lab/indextts")
INDEXTTS_PYTHON = os.path.join(INDEXTTS_DIR, ".venv/bin/python3")
ALFRED_REF = os.path.expanduser(
    "~/workshop/lab/rvc-mlx/datasets/alfred/clean_final/real_01_clean.wav"
)

_VOICE_MAP: dict[str, str] = {
    "alfred": ALFRED_REF,
}


def _available() -> bool:
    return os.path.exists(INDEXTTS_PYTHON)


@register("index-tts")
class IndexTTSEngine:
    """IndexTTS — Bilibili's zero-shot TTS, best Chinese WER."""

    name = "index-tts"

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        output_path: str | None = None,
    ) -> dict:
        if not _available():
            return {
                "error": f"IndexTTS not installed at {INDEXTTS_DIR}",
                "engine": "index-tts",
            }

        out_path = output_path or tempfile.mktemp(suffix=".wav", prefix="tts_indextts_")

        # Resolve reference audio
        ref_path = _VOICE_MAP.get(voice)
        if voice.startswith("/") and os.path.exists(voice):
            ref_path = voice
        if not ref_path:
            return {
                "error": "index-tts requires a voice reference (e.g. voice='alfred' or voice='/path/to/ref.wav')",
                "engine": "index-tts",
            }

        try:
            from . import to_simplified

            gen_text = to_simplified(text)

            result = subprocess.run(
                [
                    os.path.join(INDEXTTS_DIR, ".venv/bin/indextts"),
                    gen_text,
                    "-v",
                    ref_path,
                    "-o",
                    out_path,
                    "-d",
                    "mps",
                    "-c",
                    os.path.join(INDEXTTS_DIR, "checkpoints/config_abs.yaml"),
                    "--model_dir",
                    os.path.join(INDEXTTS_DIR, "checkpoints"),
                    "-f",  # force overwrite
                ],
                cwd=INDEXTTS_DIR,
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode != 0:
                logger.error("IndexTTS failed: %s", result.stderr[-500:] if result.stderr else "")
                return {
                    "error": f"IndexTTS subprocess failed (rc={result.returncode})",
                    "engine": "index-tts",
                }

            if not os.path.exists(out_path):
                return {"error": "IndexTTS produced no output", "engine": "index-tts"}

            import wave

            with wave.open(out_path, "rb") as wf:
                duration = wf.getnframes() / wf.getframerate()
                sample_rate = wf.getframerate()

            return {
                "audio_path": out_path,
                "duration": round(duration, 3),
                "sample_rate": sample_rate,
                "engine": "index-tts",
            }
        except subprocess.TimeoutExpired:
            return {"error": "IndexTTS timed out (300s)", "engine": "index-tts"}
        except Exception as e:
            logger.exception("IndexTTS error")
            return {"error": f"IndexTTS error: {e}", "engine": "index-tts"}

    def list_voices(self) -> list[dict]:
        return [
            {"id": "alfred", "name": "Alfred Pennyworth", "language": "en"},
        ]

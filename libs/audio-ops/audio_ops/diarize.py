"""Speaker diarization operator — subprocess-isolated pyannote.audio.

Runs in ~/.venvs/diarize/ to avoid polluting audio-ops deps with torch (~2GB).
The subprocess target is scripts/diarize_audio.py (kept as-is).

Usage:
    from audio_ops.diarize import DiarizeOp

    op = DiarizeOp()
    ctx = op({"audio_path": "/path/to/audio.wav"})
    # ctx["diarization_segments"] → [{start, end, speaker, duration}]
    # ctx["speaker_stats"] → {speaker: total_duration_seconds}
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import register

logger = logging.getLogger(__name__)

_DEFAULT_DIARIZE_VENV = Path.home() / ".venvs" / "diarize"
_DEFAULT_DIARIZE_SCRIPT = Path.home() / "workshop" / "scripts" / "diarize_audio.py"


@register("diarize")
class DiarizeOp:
    """Speaker diarization via pyannote.audio (subprocess-isolated).

    Input:  ctx["audio_path"] (str) — path to audio file (WAV, 16kHz mono recommended)
    Output: ctx["diarization_segments"] (list[dict]) — [{start, end, speaker, duration}]
            ctx["speaker_stats"] (dict) — {speaker: total_duration_seconds}
    """

    name = "diarize"
    input_keys = ("audio_path",)
    output_keys = ("diarization_segments", "speaker_stats")

    def __init__(
        self,
        venv_path: str | Path | None = None,
        script_path: str | Path | None = None,
        device: str = "auto",
    ):
        self._venv = Path(venv_path) if venv_path else _DEFAULT_DIARIZE_VENV
        self._script = Path(script_path) if script_path else _DEFAULT_DIARIZE_SCRIPT
        self._device = device

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        audio_path = Path(ctx["audio_path"]).resolve()
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        python_bin = self._venv / "bin" / "python3"
        if not python_bin.exists():
            raise FileNotFoundError(
                f"Diarize venv not found at {self._venv}. "
                "Set up: python3 -m venv ~/.venvs/diarize && "
                "~/.venvs/diarize/bin/pip install pyannote.audio torch torchaudio"
            )

        if not self._script.exists():
            raise FileNotFoundError(f"Diarize script not found: {self._script}")

        # Run diarization in isolated venv, capture JSON via temp file
        fd, output_path = tempfile.mkstemp(suffix=".json", prefix="diarize-")
        import os

        os.close(fd)

        try:
            cmd = [
                str(python_bin),
                str(self._script),
                str(audio_path),
                "--output",
                output_path,
                "--device",
                self._device,
            ]
            logger.info("Diarize: %s", " ".join(cmd))

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=1800,  # 30min for long audio (102min ≈ 15min processing)
            )

            if result.stdout:
                for line in result.stdout.strip().split("\n")[-3:]:
                    logger.info("  %s", line)

            with open(output_path) as f:
                segments = json.load(f)
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(
                f"Diarization timed out after 30 minutes for {audio_path}"
            ) from e
        except subprocess.CalledProcessError as e:
            stderr_tail = e.stderr[-500:] if e.stderr else "(no stderr)"
            raise RuntimeError(f"Diarization failed: {stderr_tail}") from e
        finally:
            Path(output_path).unlink(missing_ok=True)

        # Compute speaker stats
        stats: dict[str, float] = {}
        for seg in segments:
            stats[seg["speaker"]] = stats.get(seg["speaker"], 0) + seg["duration"]

        ctx["diarization_segments"] = segments
        ctx["speaker_stats"] = stats

        logger.info(
            "Diarize: %d segments, %d speakers (%.1f min total)",
            len(segments),
            len(stats),
            sum(stats.values()) / 60,
        )
        return ctx

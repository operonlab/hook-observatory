"""Extract audio from video files via ffmpeg.

Bridge operator: video → audio pipeline entry point.
Outputs a WAV file suitable for downstream audio-ops (denoise, diarize, etc.).

Usage:
    from audio_ops.extract_audio import ExtractAudioOp

    op = ExtractAudioOp()
    ctx = op({"video_path": "/path/to/meeting.mp4"})
    # ctx["audio_path"] → "/tmp/extract-audio-xxxx.wav"
    # ctx["audio"] and ctx["sample_rate"] also set (for direct pipeline chaining)
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import soundfile as sf

from . import register

logger = logging.getLogger(__name__)

# Extensions ffprobe reports as having audio streams
_VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv",
    ".m4v", ".ts", ".mts", ".m2ts", ".3gp",
}


def _has_audio_stream(path: str) -> bool:
    """Check if file has at least one audio stream via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-select_streams", "a",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        return "audio" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


@register("extract-audio")
class ExtractAudioOp:
    """Extract audio track from video as 16kHz mono WAV.

    Input:  ctx["video_path"] (str) — path to video file
    Output: ctx["audio_path"] (str) — path to extracted WAV (caller must clean up)
            ctx["audio"] (ndarray) — loaded audio samples (float32)
            ctx["sample_rate"] (int) — always 16000
    """

    name = "extract-audio"
    input_keys = ("video_path",)
    output_keys = ("audio_path", "audio", "sample_rate")

    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self._sample_rate = sample_rate
        self._channels = channels

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        video_path = Path(ctx["video_path"]).resolve()
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        if not _has_audio_stream(str(video_path)):
            raise ValueError(f"No audio stream found in: {video_path}")

        fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="extract-audio-")
        os.close(fd)

        try:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-vn",                          # drop video
                "-ac", str(self._channels),     # mono
                "-ar", str(self._sample_rate),  # 16kHz
                "-c:a", "pcm_s16le",            # 16-bit PCM WAV
                wav_path,
            ]
            logger.info("ExtractAudio: %s", " ".join(cmd[:6]) + " ...")

            subprocess.run(
                cmd,
                capture_output=True, text=True, check=True,
                timeout=600,  # 10min for very long videos
            )
        except subprocess.CalledProcessError as e:
            Path(wav_path).unlink(missing_ok=True)
            stderr_tail = e.stderr[-500:] if e.stderr else "(no stderr)"
            raise RuntimeError(f"ffmpeg extract audio failed: {stderr_tail}") from e
        except subprocess.TimeoutExpired as e:
            Path(wav_path).unlink(missing_ok=True)
            raise TimeoutError(
                f"Audio extraction timed out after 10 minutes for {video_path}"
            ) from e

        # Load into ctx for direct pipeline chaining
        audio, sr = sf.read(wav_path, dtype="float32")
        if audio.ndim > 1:
            audio = audio[:, 0]

        ctx["audio_path"] = wav_path
        ctx["audio"] = audio
        ctx["sample_rate"] = int(sr)

        duration = len(audio) / sr
        file_size_mb = Path(wav_path).stat().st_size / (1024 * 1024)
        logger.info(
            "ExtractAudio: %.1f min, %.1f MB → %s",
            duration / 60, file_size_mb, wav_path,
        )
        return ctx

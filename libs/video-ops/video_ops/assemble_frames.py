"""Assemble-frames operator — reassemble frame sequence into video via ffmpeg."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("assemble-frames")
class AssembleFramesOp:
    """Assemble a directory of numbered frames back into a video file.

    Expects frames named ``frame_000001.{ext}``, ``frame_000002.{ext}``, etc.
    Auto-detects the frame file extension from the first matching file.

    If ``ctx["audio_path"]`` is present, the audio track is muxed into the
    output with AAC encoding and ``-shortest`` to match durations.
    """

    name = "assemble-frames"
    input_keys = ("frames_dir", "fps")
    output_keys = ("video_path",)
    mode = "batch"

    def __init__(
        self,
        codec: str = "libx264",
        crf: int = 18,
        preset: str = "medium",
        pix_fmt: str = "yuv420p",
        ffmpeg_bin: str = "ffmpeg",
    ):
        self.codec = codec
        self.crf = crf
        self.preset = preset
        self.pix_fmt = pix_fmt
        self.ffmpeg_bin = ffmpeg_bin

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        frames_dir = ctx["frames_dir"]
        fps = ctx["fps"]

        # Detect frame extension from directory contents
        ext = _detect_frame_ext(frames_dir)
        input_pattern = os.path.join(frames_dir, f"frame_%06d.{ext}")

        # Create output temp file
        fd, output_path = tempfile.mkstemp(suffix=".mp4", prefix="assembled-")
        os.close(fd)

        cmd = [
            self.ffmpeg_bin, "-y",
            "-framerate", str(fps),
            "-i", input_pattern,
        ]

        # Mux audio if available
        audio_path = ctx.get("audio_path")
        if audio_path:
            cmd.extend(["-i", audio_path, "-c:a", "aac", "-shortest"])

        cmd.extend([
            "-c:v", self.codec,
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-pix_fmt", self.pix_fmt,
            "-movflags", "+faststart",
            output_path,
        ])

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
        )

        if result.returncode != 0:
            # Clean up partial output on failure
            if os.path.exists(output_path):
                os.unlink(output_path)
            raise RuntimeError(
                f"ffmpeg assemble-frames failed (rc={result.returncode}): "
                f"{result.stderr.strip()[-500:]}"
            )

        ctx["video_path"] = output_path

        logger.info(
            "assemble-frames: %s -> %s (fps=%.2f, codec=%s, crf=%d)",
            frames_dir, output_path, fps, self.codec, self.crf,
        )

        return ctx


def _detect_frame_ext(frames_dir: str) -> str:
    """Detect frame file extension by scanning the directory."""
    for fname in sorted(os.listdir(frames_dir)):
        if fname.startswith("frame_") and "." in fname:
            return fname.rsplit(".", 1)[1]
    raise FileNotFoundError(
        f"No frame files (frame_*.ext) found in {frames_dir}"
    )

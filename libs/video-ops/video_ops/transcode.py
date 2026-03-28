"""Transcode operator — re-encode video with configurable codec/quality via ffmpeg."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("transcode")
class TranscodeOp:
    """Re-encode video with a target codec, CRF, preset, and pixel format.

    Produces an MP4 with ``-movflags +faststart`` for web streaming.
    Audio is re-encoded to AAC.  The original file is left untouched;
    the new path is written back to ``ctx["video_path"]``.
    """

    name = "transcode"
    input_keys = ("video_path",)
    output_keys = ("video_path", "codec")
    mode = "batch"

    def __init__(
        self,
        codec: str = "libx264",
        crf: int = 23,
        preset: str = "medium",
        pix_fmt: str = "yuv420p",
    ):
        self.codec = codec
        self.crf = crf
        self.preset = preset
        self.pix_fmt = pix_fmt

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        video_path = ctx["video_path"]

        fd, out_path = tempfile.mkstemp(suffix=".mp4", prefix="transcode-")
        os.close(fd)

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-c:v", self.codec,
            "-crf", str(self.crf),
            "-preset", self.preset,
            "-pix_fmt", self.pix_fmt,
            "-c:a", "aac",
            "-movflags", "+faststart",
            out_path,
        ]

        logger.info("transcode: %s", " ".join(cmd[:8]) + " ...")

        try:
            subprocess.run(
                cmd,
                capture_output=True, text=True, check=True,
                timeout=600,
            )
        except subprocess.CalledProcessError as e:
            Path(out_path).unlink(missing_ok=True)
            stderr_tail = e.stderr[-500:] if e.stderr else "(no stderr)"
            raise RuntimeError(f"ffmpeg transcode failed: {stderr_tail}") from e
        except subprocess.TimeoutExpired as e:
            Path(out_path).unlink(missing_ok=True)
            raise TimeoutError(
                f"Transcode timed out after 600s for {video_path}"
            ) from e

        out_size_mb = Path(out_path).stat().st_size / (1024 * 1024)
        logger.info(
            "transcode: %s -> %s (%.1f MB, codec=%s, crf=%d, preset=%s)",
            video_path, out_path, out_size_mb, self.codec, self.crf, self.preset,
        )

        ctx["video_path"] = out_path
        ctx["codec"] = self.codec
        return ctx

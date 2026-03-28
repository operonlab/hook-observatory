"""Thumbnail operator — extract a single frame as JPEG via ffmpeg."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import register

logger = logging.getLogger(__name__)


def _probe_duration(video_path: str) -> float:
    """Get video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        video_path,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
    except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        pass
    return 0.0


@register("thumbnail")
class ThumbnailOp:
    """Extract a single video frame as a JPEG thumbnail.

    If ``time`` is not specified, the frame at 50% of the video duration
    is used (read from ``ctx["duration"]`` or probed via ffprobe).

    Height defaults to ``-2`` (ffmpeg auto-calculates to preserve aspect
    ratio while keeping the value even, which is required by most codecs).
    """

    name = "thumbnail"
    input_keys = ("video_path",)
    output_keys = ("thumbnail_path",)
    mode = "batch"

    def __init__(
        self,
        time: float | None = None,
        width: int = 320,
        height: int = -1,
    ):
        self.time = time
        self.width = width
        # ffmpeg requires even dimensions; -2 auto-adjusts to nearest even
        self.height = -2 if height == -1 else height

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        video_path = ctx["video_path"]

        # Determine capture time
        capture_time = self.time
        if capture_time is None:
            duration = ctx.get("duration")
            if duration is None or duration <= 0:
                duration = _probe_duration(video_path)
            capture_time = duration * 0.5 if duration > 0 else 0.0

        fd, out_path = tempfile.mkstemp(suffix=".jpg", prefix="thumb-")
        os.close(fd)

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(capture_time),
            "-i", video_path,
            "-vframes", "1",
            "-vf", f"scale={self.width}:{self.height}",
            out_path,
        ]

        logger.info("thumbnail: %s @ %.1fs", video_path, capture_time)

        try:
            subprocess.run(
                cmd,
                capture_output=True, text=True, check=True,
                timeout=30,
            )
        except subprocess.CalledProcessError as e:
            Path(out_path).unlink(missing_ok=True)
            stderr_tail = e.stderr[-500:] if e.stderr else "(no stderr)"
            raise RuntimeError(f"ffmpeg thumbnail failed: {stderr_tail}") from e
        except subprocess.TimeoutExpired as e:
            Path(out_path).unlink(missing_ok=True)
            raise TimeoutError(
                f"Thumbnail extraction timed out after 30s for {video_path}"
            ) from e

        out_size_kb = Path(out_path).stat().st_size / 1024
        logger.info(
            "thumbnail: %s -> %s (%.1f KB, %dx%s @ %.1fs)",
            video_path, out_path, out_size_kb,
            self.width, self.height, capture_time,
        )

        ctx["thumbnail_path"] = out_path
        return ctx

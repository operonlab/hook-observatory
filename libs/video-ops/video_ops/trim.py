"""Trim operator — fast-cut a video segment via ffmpeg stream copy."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("trim")
class TrimOp:
    """Trim a video to a time range using ``-c copy`` (no re-encoding).

    Specify either ``end`` (absolute time) or ``duration`` (relative length).
    If both ``end`` and ``duration`` are None, the operator is a no-op.
    """

    name = "trim"
    input_keys = ("video_path",)
    output_keys = ("video_path", "duration")
    mode = "batch"

    def __init__(
        self,
        start: float = 0.0,
        end: float | None = None,
        duration: float | None = None,
    ):
        self.start = start
        self.end = end
        self.duration = duration

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        # No-op when no trim range specified
        if self.end is None and self.duration is None:
            return ctx

        video_path = ctx["video_path"]

        fd, out_path = tempfile.mkstemp(suffix=".mp4", prefix="trim-")
        os.close(fd)

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(self.start),
        ]

        if self.end is not None:
            cmd.extend(["-to", str(self.end)])

        if self.duration is not None:
            cmd.extend(["-t", str(self.duration)])

        cmd.extend([
            "-i", video_path,
            "-c", "copy",
            out_path,
        ])

        logger.info("trim: %s", " ".join(cmd))

        try:
            subprocess.run(
                cmd,
                capture_output=True, text=True, check=True,
                timeout=120,
            )
        except subprocess.CalledProcessError as e:
            Path(out_path).unlink(missing_ok=True)
            stderr_tail = e.stderr[-500:] if e.stderr else "(no stderr)"
            raise RuntimeError(f"ffmpeg trim failed: {stderr_tail}") from e
        except subprocess.TimeoutExpired as e:
            Path(out_path).unlink(missing_ok=True)
            raise TimeoutError(
                f"Trim timed out after 120s for {video_path}"
            ) from e

        # Calculate actual duration of trimmed segment
        if self.end is not None:
            trimmed_duration = self.end - self.start
        elif self.duration is not None:
            trimmed_duration = self.duration
        else:
            trimmed_duration = 0.0

        out_size_mb = Path(out_path).stat().st_size / (1024 * 1024)
        logger.info(
            "trim: %s -> %s (%.1f MB, %.1fs-%.1fs, ~%.1fs)",
            video_path,
            out_path,
            out_size_mb,
            self.start,
            self.end if self.end is not None else self.start + (self.duration or 0),
            trimmed_duration,
        )

        ctx["video_path"] = out_path
        ctx["duration"] = trimmed_duration
        return ctx

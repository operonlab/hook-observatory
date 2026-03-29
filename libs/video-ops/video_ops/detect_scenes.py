"""Detect-scenes operator -- find scene boundaries via ffmpeg scene detection filter."""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Any

from . import register

logger = logging.getLogger(__name__)

_PTS_RE = re.compile(r"pts_time:\s*([\d.]+)")


@register("detect-scenes")
class DetectScenesOp:
    """Detect scene boundaries using ffmpeg's scene change detection filter.

    Runs ``select='gt(scene,{threshold})',showinfo`` and parses ``pts_time:``
    values from stderr.  Returns a sorted list of timestamps (seconds) where
    scene changes were detected.

    Lower *threshold* (0.0-1.0) produces more boundaries; 0.3 is a good
    starting point for most content.
    """

    name = "detect-scenes"
    input_keys = ("video_path",)
    output_keys = ("scene_boundaries",)
    mode = "batch"

    def __init__(self, threshold: float = 0.3, ffmpeg_bin: str = "ffmpeg"):
        self.threshold = float(threshold)
        self.ffmpeg_bin = ffmpeg_bin

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        video_path = ctx["video_path"]

        cmd = [
            self.ffmpeg_bin,
            "-i", video_path,
            "-vf", f"select='gt(scene,{self.threshold})',showinfo",
            "-f", "null",
            "-",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            logger.error("detect-scenes: timed out after 300s for %s", video_path)
            ctx["scene_boundaries"] = []
            return ctx
        except OSError as exc:
            logger.error("detect-scenes: failed to run ffmpeg: %s", exc)
            ctx["scene_boundaries"] = []
            return ctx

        # Scene info is written to stderr by showinfo filter
        stderr = result.stderr or ""
        timestamps = sorted(float(m) for m in _PTS_RE.findall(stderr))

        ctx["scene_boundaries"] = timestamps

        logger.info(
            "detect-scenes: %s -- %d scene boundaries found (threshold=%.2f)",
            video_path,
            len(timestamps),
            self.threshold,
        )

        return ctx

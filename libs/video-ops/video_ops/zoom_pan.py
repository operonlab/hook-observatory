"""Zoom-pan operator -- Ken Burns zoom/pan effect via ffmpeg zoompan filter."""

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


@register("zoom-pan")
class ZoomPanOp:
    """Apply Ken Burns zoom/pan effect using ffmpeg's zoompan filter.

    Smoothly zooms from *zoom_start* to *zoom_end* over the video duration.
    The *x* and *y* expressions control the pan center (ffmpeg expr syntax).
    Defaults centre the zoom on the frame.

    If *duration* is ``None``, the operator reads ``ctx["duration"]`` (set
    by :class:`ProbeOp`).  If that is also missing it probes the input via
    ffprobe automatically.
    """

    name = "zoom-pan"
    input_keys = ("video_path",)
    output_keys = ("video_path",)
    mode = "batch"

    def __init__(
        self,
        zoom_start: float = 1.0,
        zoom_end: float = 1.5,
        x: str = "iw/2-(iw/zoom/2)",
        y: str = "ih/2-(ih/zoom/2)",
        duration: float | None = None,
        fps: int = 30,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
    ):
        self.zoom_start = float(zoom_start)
        self.zoom_end = float(zoom_end)
        self.x = str(x)
        self.y = str(y)
        self.duration = float(duration) if duration is not None else None
        self.fps = int(fps)
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        video_path = ctx["video_path"]

        # Resolve duration
        dur = self.duration or ctx.get("duration")
        if dur is None or dur <= 0:
            dur = self._probe_duration(video_path)
        if dur is None or dur <= 0:
            logger.error("zoom-pan: cannot determine duration for %s", video_path)
            return ctx

        # Resolve dimensions from ctx or probe
        width = ctx.get("width")
        height = ctx.get("height")
        if not width or not height:
            width, height = self._probe_dimensions(video_path)
        if not width or not height:
            logger.error("zoom-pan: cannot determine dimensions for %s", video_path)
            return ctx

        total_frames = self.fps * dur
        if total_frames <= 0:
            logger.warning("zoom-pan: total_frames=0, skipping")
            return ctx

        increment = (self.zoom_end - self.zoom_start) / total_frames

        # Build zoompan filter expression
        # d=1 means each input frame produces 1 output frame (we re-time via fps)
        zoom_expr = f"min({self.zoom_start}+on*{increment},{self.zoom_end})"
        vf = (
            f"zoompan=z='{zoom_expr}'"
            f":x='{self.x}':y='{self.y}'"
            f":d=1:s={width}x{height}:fps={self.fps}"
        )

        fd, out_path = tempfile.mkstemp(suffix=".mp4", prefix="zoompan-")
        os.close(fd)

        cmd = [
            self.ffmpeg_bin, "-y",
            "-i", video_path,
            "-vf", vf,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            out_path,
        ]

        logger.info("zoom-pan: %s", " ".join(cmd[:8]) + " ...")

        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=600,
            )
        except subprocess.CalledProcessError as exc:
            Path(out_path).unlink(missing_ok=True)
            stderr_tail = exc.stderr[-500:] if exc.stderr else "(no stderr)"
            raise RuntimeError(f"ffmpeg zoom-pan failed: {stderr_tail}") from exc
        except subprocess.TimeoutExpired as exc:
            Path(out_path).unlink(missing_ok=True)
            raise TimeoutError(
                f"zoom-pan timed out after 600s for {video_path}"
            ) from exc

        out_size_mb = Path(out_path).stat().st_size / (1024 * 1024)
        logger.info(
            "zoom-pan: %s -> %s (%.1f MB, zoom %.1f->%.1f, %ds @ %d fps)",
            video_path,
            out_path,
            out_size_mb,
            self.zoom_start,
            self.zoom_end,
            dur,
            self.fps,
        )

        ctx["video_path"] = out_path
        return ctx

    # -- helpers ---------------------------------------------------------------

    def _probe_duration(self, path: str) -> float | None:
        """Quick ffprobe to get duration."""
        try:
            result = subprocess.run(
                [
                    self.ffprobe_bin, "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    path,
                ],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return float(data.get("format", {}).get("duration", 0))
        except Exception as exc:
            logger.warning("zoom-pan: ffprobe duration failed: %s", exc)
        return None

    def _probe_dimensions(self, path: str) -> tuple[int | None, int | None]:
        """Quick ffprobe to get width/height."""
        try:
            result = subprocess.run(
                [
                    self.ffprobe_bin, "-v", "quiet",
                    "-print_format", "json",
                    "-show_streams",
                    path,
                ],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "video":
                        return int(stream["width"]), int(stream["height"])
        except Exception as exc:
            logger.warning("zoom-pan: ffprobe dimensions failed: %s", exc)
        return None, None

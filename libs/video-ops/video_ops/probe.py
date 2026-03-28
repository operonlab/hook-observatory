"""Probe operator — extract video metadata via ffprobe."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("probe")
class ProbeOp:
    """Extract video metadata (resolution, fps, codec, duration) via ffprobe.

    Reads the first video stream and format info.  Stores the full JSON
    output as ``ctx["metadata"]`` for downstream operators that need
    additional fields.
    """

    name = "probe"
    input_keys = ("video_path",)
    output_keys = ("fps", "frame_count", "duration", "width", "height", "codec", "metadata")
    mode = "batch"

    def __init__(self, ffprobe_bin: str = "ffprobe"):
        self.ffprobe_bin = ffprobe_bin

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        video_path = ctx["video_path"]

        cmd = [
            self.ffprobe_bin,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            raise RuntimeError(
                f"ffprobe failed (rc={result.returncode}): {result.stderr.strip()}"
            )

        data = json.loads(result.stdout)

        # Find first video stream
        video_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_stream = stream
                break

        if video_stream is None:
            raise ValueError(f"No video stream found in {video_path}")

        # Parse r_frame_rate ("30/1" -> 30.0, "30000/1001" -> 29.97)
        fps = _parse_frame_rate(video_stream.get("r_frame_rate", "0/1"))

        # nb_frames may be "N/A" or missing for some containers
        nb_frames_raw = video_stream.get("nb_frames", "0")
        try:
            frame_count = int(nb_frames_raw)
        except (ValueError, TypeError):
            # Estimate from duration * fps
            fmt_duration = float(data.get("format", {}).get("duration", 0))
            frame_count = int(fmt_duration * fps) if fps > 0 else 0

        duration = float(data.get("format", {}).get("duration", 0))

        ctx["fps"] = fps
        ctx["frame_count"] = frame_count
        ctx["duration"] = duration
        ctx["width"] = int(video_stream.get("width", 0))
        ctx["height"] = int(video_stream.get("height", 0))
        ctx["codec"] = video_stream.get("codec_name", "unknown")
        ctx["metadata"] = data

        logger.info(
            "probe: %s — %dx%d, %.2f fps, %d frames, %.1fs, codec=%s",
            video_path,
            ctx["width"],
            ctx["height"],
            ctx["fps"],
            ctx["frame_count"],
            ctx["duration"],
            ctx["codec"],
        )

        return ctx


def _parse_frame_rate(rate_str: str) -> float:
    """Parse ffprobe r_frame_rate string (e.g. '30/1', '30000/1001')."""
    if "/" in rate_str:
        num, den = rate_str.split("/", 1)
        try:
            numerator = float(num)
            denominator = float(den)
            if denominator == 0:
                return 0.0
            return numerator / denominator
        except ValueError:
            return 0.0
    try:
        return float(rate_str)
    except ValueError:
        return 0.0

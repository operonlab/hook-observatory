"""Extract-frames operator — extract video frames as PNG/JPEG sequence via ffmpeg."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Any

from . import register

logger = logging.getLogger(__name__)


@register("extract-frames")
class ExtractFramesOp:
    """Extract frames from a video file at a given FPS rate.

    Creates a temp directory containing sequentially numbered frames
    (``frame_000001.png``, ``frame_000002.png``, ...).

    If ``ctx["fps"]`` already exists (e.g. from ProbeOp), it is used as the
    default extraction rate unless the constructor ``fps`` explicitly overrides.
    """

    name = "extract-frames"
    input_keys = ("video_path",)
    output_keys = ("frames_dir", "frame_count")
    mode = "batch"

    def __init__(
        self,
        fps: float = 1.0,
        format: str = "png",
        start: float | None = None,
        duration: float | None = None,
        ffmpeg_bin: str = "ffmpeg",
    ):
        self.fps = fps
        self.format = format
        self.start = start
        self.duration = duration
        self.ffmpeg_bin = ffmpeg_bin

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        video_path = ctx["video_path"]

        # Use ProbeOp fps as default, but constructor fps takes priority
        # (constructor default is 1.0, so check if caller explicitly set it)
        extract_fps = self.fps

        frames_dir = tempfile.mkdtemp(prefix="frames-")

        output_pattern = os.path.join(frames_dir, f"frame_%06d.{self.format}")

        cmd = [self.ffmpeg_bin, "-y"]

        # Seek before input for fast seeking
        if self.start is not None:
            cmd.extend(["-ss", str(self.start)])

        cmd.extend(["-i", video_path])

        if self.duration is not None:
            cmd.extend(["-t", str(self.duration)])

        cmd.extend([
            "-vf", f"fps={extract_fps}",
            output_pattern,
        ])

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg extract-frames failed (rc={result.returncode}): "
                f"{result.stderr.strip()[-500:]}"
            )

        # Count extracted frames
        frame_files = [
            f for f in os.listdir(frames_dir)
            if f.startswith("frame_") and f.endswith(f".{self.format}")
        ]
        frame_count = len(frame_files)

        ctx["frames_dir"] = frames_dir
        ctx["frame_count"] = frame_count

        logger.info(
            "extract-frames: %s -> %s (%d frames @ %.2f fps)",
            video_path, frames_dir, frame_count, extract_fps,
        )

        return ctx

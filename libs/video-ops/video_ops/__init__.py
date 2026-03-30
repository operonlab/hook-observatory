"""Video operators — composable ffmpeg-based video transforms.

Inherits from ops_core (shared protocol + combinators).

Usage:
    from video_ops import parse_operators, VideoPipeline
    ops = parse_operators("probe,extract-frames:fps=2")
    pipeline = VideoPipeline().pipe(*ops)
    ctx = pipeline.execute({"video_path": "/path/to/video.mp4"})

    # Or fluent style:
    VideoPipeline.from_file("vid.mp4").pipe(ProbeOp(), TrimOp(start=10)).execute()
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ops_core import (  # noqa: F401 — re-export for backward compat
    BasePipeline,
    BaseStream,
    BufferCount,
    CatchOp,
    ConditionalOp,
    Filter,
    ParallelOp,
    Skip,
    Take,
    TapOp,
    Throttle,
    parse_spec,
)
from ops_core import (
    Op as VideoOp,
)

logger = logging.getLogger(__name__)

# ── Backend abstraction (future: gstreamer | deepstream) ──────────────

BACKEND = "ffmpeg"


def get_backend() -> str:
    """Get video processing backend. Future: 'gstreamer' | 'deepstream'."""
    return os.environ.get("VIDEO_OPS_BACKEND", "ffmpeg")


# ── VideoPipeline ────────────────────────────────────────────────────────


class VideoPipeline(BasePipeline):
    """Video-specific pipeline with from_file(path).

    No of() — video is always file-based (ffmpeg subprocess).
    """

    @classmethod
    def from_file(cls, path: str | Path, **extra) -> VideoPipeline:
        """from() — create pipeline from video file path."""
        return cls._create(
            {
                "video_path": str(path),
                "source_path": str(path),
                **extra,
            }
        )

    def _repr_source(self) -> str:
        if self._initial_ctx and "source_path" in self._initial_ctx:
            return f"from({self._initial_ctx['source_path']}) -> "
        return ""


# ── VideoStream (streaming pipeline) ─────────────────────────────────────


class VideoStream(BaseStream):
    """Streaming video pipeline — for frame-by-frame processing.

    Usage:
        VideoStream.from_frames(frame_gen).pipe(
            Throttle(1/24),
            GrayscaleOp(),
        ).subscribe(lambda ctx: display(ctx["image"]))
    """

    @classmethod
    def from_frames(cls, source: Iterable) -> VideoStream:
        """Create stream from video frame generator.

        Source yields np.ndarray frames or dicts with 'image' key.
        """

        def _wrap():
            for i, item in enumerate(source):
                if isinstance(item, dict):
                    yield item
                else:
                    h, w = item.shape[:2]
                    yield {"image": item, "width": w, "height": h, "frame_idx": i}

        return cls(_wrap())


# ── Registry ────────────────────────────────────────────────────────────

OPERATORS: dict[str, type] = {}


def register(name: str):
    """Decorator to register an operator class."""

    def wrapper(cls):
        OPERATORS[name] = cls
        return cls

    return wrapper


# Import operators to trigger registration
def _register_builtins():
    from . import (  # noqa: F401
        assemble_frames,
        detect_scenes,
        extract_frames,
        map_frames,
        probe,
        thumbnail,
        transcode,
        trim,
        yolo_overlay,
        zoom_pan,
    )


_register_builtins()


# -- Parser -----------------------------------------------------------------


def _make_op(name: str, kwargs: dict) -> VideoOp:
    if name not in OPERATORS:
        raise ValueError(f"Unknown operator: '{name}'. Available: {list(OPERATORS.keys())}")
    return OPERATORS[name](**kwargs)


def parse_operators(spec: str, sep: str = ",") -> list[VideoOp]:
    """Parse operator spec string with [a+b] parallel support."""
    return parse_spec(spec, _make_op, sep=sep)


# ── Processing Runner ─────────────────────────────────────────────────


def run_processing(file_path: str, ops: list[VideoOp]) -> str:
    """Run video operator pipeline on a file.

    Returns the final video_path from context (may be a temp file).
    Returns original file_path if ops is empty.
    """
    if not ops:
        return file_path

    ctx: dict[str, Any] = {
        "video_path": file_path,
        "source_path": file_path,
    }

    pipeline = VideoPipeline().pipe(*ops)
    missing = pipeline.compile(set(ctx.keys()))
    if missing:
        raise ValueError(f"Pipeline key validation failed: {missing}")

    ctx = pipeline.execute(ctx)
    logger.info("Processing: %s → %s", pipeline, ctx.get("video_path", file_path))

    return ctx.get("video_path", file_path)

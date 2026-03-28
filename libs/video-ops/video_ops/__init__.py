"""Video operators — composable ffmpeg-based video transforms.

RxJS-inspired Operator Protocol — same interface as audio_ops and image_ops,
but specialised for video processing via ffmpeg/ffprobe subprocess calls.

Usage:
    from video_ops import parse_operators, VideoPipeline
    ops = parse_operators("probe,extract-frames:fps=2")
    pipeline = VideoPipeline().pipe(*ops)
    ctx = pipeline.execute({"video_path": "/path/to/video.mp4"})

    # Bridge to image_ops
    ops = parse_operators("extract-frames:fps=1,map-frames:image_ops=grayscale|clahe")
"""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ── Backend abstraction (future: gstreamer | deepstream) ──────────────

BACKEND = "ffmpeg"


def get_backend() -> str:
    """Get video processing backend. Future: 'gstreamer' | 'deepstream'."""
    return os.environ.get("VIDEO_OPS_BACKEND", "ffmpeg")


# -- VideoOp Protocol (mirrors audio_ops.AudioOp / image_ops.ImageOp) ------


@runtime_checkable
class VideoOp(Protocol):
    """Pure function video transform — subprocess-based ffmpeg operator.

    Sync __call__ because all video operators shell out to ffmpeg (CPU-bound).
    """

    @property
    def name(self) -> str: ...

    @property
    def input_keys(self) -> tuple[str, ...]: ...

    @property
    def output_keys(self) -> tuple[str, ...]: ...

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]: ...


# ── VideoPipeline (simplified from core Pipeline) ──────────────────────


class VideoPipeline:
    """Composable operator chain with static key validation."""

    def __init__(self) -> None:
        self._ops: list[VideoOp] = []

    def pipe(self, *ops: VideoOp) -> VideoPipeline:
        self._ops.extend(ops)
        return self

    def compile(self, initial_keys: set[str] | None = None) -> list[str]:
        available = set(initial_keys) if initial_keys else set()
        missing: list[str] = []
        for op in self._ops:
            for key in op.input_keys:
                if key not in available:
                    missing.append(f"{op.name}: requires '{key}'")
            for key in op.output_keys:
                available.add(key)
        return missing

    def execute(self, ctx: dict[str, Any]) -> dict[str, Any]:
        for op in self._ops:
            ctx = op(ctx)
        return ctx

    def __repr__(self) -> str:
        names = " -> ".join(op.name for op in self._ops)
        return f"VideoPipeline({names})"

    def __len__(self) -> int:
        return len(self._ops)


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
        extract_frames,
        map_frames,
        probe,
        thumbnail,
        transcode,
        trim,
    )


_register_builtins()


# -- Parser -----------------------------------------------------------------


def parse_operators(spec: str, sep: str = ",") -> list[VideoOp]:
    """Parse operator spec string into instantiated operators.

    Format: "probe,extract-frames:fps=2,map-frames:image_ops=grayscale|clahe"

    Args:
        spec: Operator specification string.
        sep: Token separator. Defaults to comma.
    """
    ops = []
    for token in spec.split(sep):
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            name, params_str = token.split(":", 1)
            kwargs = {}
            for pair in params_str.split(";"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    try:
                        kwargs[k.strip()] = float(v.strip())
                    except ValueError:
                        kwargs[k.strip()] = v.strip()
            ops.append(_make_op(name.strip(), kwargs))
        else:
            ops.append(_make_op(token, {}))
    return ops


def _make_op(name: str, kwargs: dict) -> VideoOp:
    if name not in OPERATORS:
        raise ValueError(f"Unknown operator: '{name}'. Available: {list(OPERATORS.keys())}")
    return OPERATORS[name](**kwargs)


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

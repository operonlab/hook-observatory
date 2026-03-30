"""Video operators — composable ffmpeg-based video transforms.

Inherits from ops_core.BasePipe (unified batch + streaming).

Usage:
    # Batch
    VideoPipe.from_file("vid.mp4").pipe(ProbeOp(), TrimOp(start=10)).execute()

    # Streaming
    VideoPipe.from_frames(frame_gen).pipe(
        Throttle(1/24), GrayscaleOp(),
    ).subscribe(callback)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ops_core import (  # noqa: F401 — re-export for backward compat
    BasePipe,
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
from ops_core import Op as VideoOp

logger = logging.getLogger(__name__)

BACKEND = "ffmpeg"


def get_backend() -> str:
    return os.environ.get("VIDEO_OPS_BACKEND", "ffmpeg")


# ── VideoPipe ────────────────────────────────────────────────────────────


class VideoPipe(BasePipe):
    """Unified video pipe — batch or streaming, decided by source."""

    # ── Batch sources ────────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: str | Path, **extra) -> VideoPipe:
        """from() — create pipe from video file path."""
        return cls._create_batch(
            {
                "video_path": str(path),
                "source_path": str(path),
                **extra,
            }
        )

    # ── Streaming sources ────────────────────────────────────────────

    @classmethod
    def from_frames(cls, source: Iterable) -> VideoPipe:
        """from_frames() — stream from video frame generator."""

        def _wrap():
            for i, item in enumerate(source):
                if isinstance(item, dict):
                    yield item
                else:
                    h, w = item.shape[:2]
                    yield {"image": item, "width": w, "height": h, "frame_idx": i}

        return cls._create_stream(_wrap())

    # ── Repr ─────────────────────────────────────────────────────────

    def _repr_source(self) -> str:
        if self._initial_ctx and "source_path" in self._initial_ctx:
            return f"from({self._initial_ctx['source_path']}) -> "
        elif self._is_streaming:
            return "frames -> "
        return ""


# Backward compat
VideoPipeline = VideoPipe
VideoStream = VideoPipe


# ── Registry ────────────────────────────────────────────────────────────

OPERATORS: dict[str, type] = {}


def register(name: str):
    def wrapper(cls):
        OPERATORS[name] = cls
        return cls

    return wrapper


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
    return parse_spec(spec, _make_op, sep=sep)


# ── Processing Runner ─────────────────────────────────────────────────


def run_processing(file_path: str, ops: list[VideoOp]) -> str:
    if not ops:
        return file_path

    ctx: dict[str, Any] = {"video_path": file_path, "source_path": file_path}

    pipeline = VideoPipe().pipe(*ops)
    missing = pipeline.compile(set(ctx.keys()))
    if missing:
        raise ValueError(f"Pipeline key validation failed: {missing}")

    ctx = pipeline.execute(ctx)
    return ctx.get("video_path", file_path)

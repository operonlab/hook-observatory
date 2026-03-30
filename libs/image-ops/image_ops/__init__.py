"""Image operators — OCR preprocessing pipeline for vision, capture, and paper modules.

Inherits from ops_core (shared protocol + combinators).

Usage:
    from image_ops import parse_operators, run_preprocessing
    ops = parse_operators("grayscale,clahe,denoise,deskew")
    processed_path = run_preprocessing("/path/to/scan.png", ops)

    from image_ops import ImagePipeline
    ImagePipeline.from_file("scan.png").pipe(GrayscaleOp(), ClaheOp()).execute()
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterable
from typing import Any

import numpy as np
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
    Op as ImageOp,
)

logger = logging.getLogger(__name__)


# ── ImagePipeline ────────────────────────────────────────────────────────


class ImagePipeline(BasePipeline):
    """Image-specific pipeline with of(array) and from_file(path)."""

    @classmethod
    def of(cls, image: np.ndarray, **extra) -> ImagePipeline:
        """of() — wrap in-memory image array into a pipeline."""
        h, w = image.shape[:2]
        return cls._create(
            {
                "image": image,
                "width": w,
                "height": h,
                "color_space": extra.pop("color_space", "rgb"),
                **extra,
            }
        )

    @classmethod
    def from_file(cls, path: str, **extra) -> ImagePipeline:
        """from() — read image file into a pipeline."""
        try:
            import cv2

            img = cv2.imread(str(path))
            color_space = "bgr"
        except ImportError:
            from PIL import Image

            img = np.array(Image.open(str(path)))
            color_space = "rgb"
        if img is None:
            raise ValueError(f"Failed to load image: {path}")
        h, w = img.shape[:2]
        return cls._create(
            {
                "image": img,
                "width": w,
                "height": h,
                "color_space": color_space,
                "image_path": str(path),
                "source_path": str(path),
                **extra,
            }
        )

    def _repr_source(self) -> str:
        if self._initial_ctx and "source_path" in self._initial_ctx:
            return f"from({self._initial_ctx['source_path']}) -> "
        elif self._initial_ctx:
            w = self._initial_ctx.get("width", "?")
            h = self._initial_ctx.get("height", "?")
            return f"of({w}x{h}) -> "
        return ""


# ── ImageStream (streaming pipeline) ─────────────────────────────────────


class ImageStream(BaseStream):
    """Streaming image pipeline — for frame-by-frame processing.

    Usage:
        ImageStream.from_frames(camera_gen).pipe(
            Throttle(1/30),      # 30 fps cap
            GrayscaleOp(),       # batch op, auto-lifted
            DetectOp(),
        ).subscribe(lambda ctx: overlay(ctx))
    """

    @classmethod
    def from_frames(cls, source: Iterable) -> ImageStream:
        """Create stream from image frame generator.

        Source yields np.ndarray frames or dicts with 'image' key.
        """

        def _wrap():
            for item in source:
                if isinstance(item, dict):
                    yield item
                else:
                    h, w = item.shape[:2]
                    yield {"image": item, "width": w, "height": h, "color_space": "rgb"}

        return cls(_wrap())


# ── Registry ─────────────────────────────────────────────────────────────

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
        auto_enhance,
        clahe,
        contrast,
        denoise,
        deskew,
        detect,
        grayscale,
        invert,
        resize,
    )


_register_builtins()


# ── Parser ───────────────────────────────────────────────────────────────


def _make_op(name: str, kwargs: dict) -> ImageOp:
    if name not in OPERATORS:
        raise ValueError(f"Unknown operator: '{name}'. Available: {list(OPERATORS.keys())}")
    return OPERATORS[name](**kwargs)


def parse_operators(spec: str, sep: str = ",") -> list[ImageOp]:
    """Parse operator spec string with [a+b] parallel support.

    Args:
        spec: e.g. "grayscale,clahe:clip_limit=3.0,[denoise+deskew]"
        sep: Token separator. Defaults to comma; use "|" for MapFramesOp.
    """
    return parse_spec(spec, _make_op, sep=sep)


# ── Preprocessing Runner ─────────────────────────────────────────────────


def run_preprocessing(file_path: str, ops: list[ImageOp]) -> str:
    """Load image, run operator pipeline, write temp file.

    Returns the original file_path if ops is empty,
    otherwise a temp PNG path (caller must clean up).
    """
    if not ops:
        return file_path

    try:
        import cv2

        img = cv2.imread(file_path)
        color_space = "bgr"
    except ImportError:
        from PIL import Image

        img = np.array(Image.open(file_path))
        color_space = "rgb"

    if img is None:
        raise ValueError(f"Failed to load image: {file_path}")

    h, w = img.shape[:2]
    ctx: dict[str, Any] = {
        "image": img,
        "image_path": file_path,
        "width": w,
        "height": h,
        "color_space": color_space,
        "source_path": file_path,
    }

    pipeline = ImagePipeline().pipe(*ops)
    missing = pipeline.compile(set(ctx.keys()))
    if missing:
        raise ValueError(f"Pipeline key validation failed: {missing}")

    ctx = pipeline.execute(ctx)

    fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="image-op-")
    os.close(fd)

    try:
        import cv2

        cv2.imwrite(tmp_path, ctx["image"])
    except ImportError:
        from PIL import Image

        Image.fromarray(ctx["image"]).save(tmp_path)

    new_w, new_h = ctx.get("width", w), ctx.get("height", h)
    logger.info("Preprocessing: %s (%dx%d -> %dx%d)", pipeline, w, h, new_w, new_h)

    return tmp_path

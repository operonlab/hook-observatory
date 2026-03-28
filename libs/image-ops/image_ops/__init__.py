"""Image operators — OCR preprocessing pipeline for vision, capture, and paper modules.

RxJS-inspired Operator Protocol — same interface as core/src/shared/reactive.py
and audio_ops, but specialised for image transforms.

Originally extracted from OCR preprocessing logic to enable composable,
reusable image transforms across the workshop.

Usage:
    from image_ops import parse_operators, run_preprocessing
    ops = parse_operators("grayscale,clahe,denoise,deskew")
    processed_path = run_preprocessing("/path/to/scan.png", ops)

    # With parameters
    ops = parse_operators("resize:width=800,clahe:clip_limit=3.0")

    # Pipe-separated (for MapFramesOp integration)
    ops = parse_operators("grayscale|contrast:alpha=1.5", sep="|")
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── ImageOp Protocol (mirrors core/src/shared/reactive.Operator) ─────────


@runtime_checkable
class ImageOp(Protocol):
    """Pure function image transform — the GCF of all preprocessing stages.

    Sync __call__ because all image operators are CPU-bound (no async I/O).
    This avoids event loop conflicts when called from FastAPI via to_thread().
    """

    @property
    def name(self) -> str: ...

    @property
    def input_keys(self) -> tuple[str, ...]: ...

    @property
    def output_keys(self) -> tuple[str, ...]: ...

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]: ...


# ── ImagePipeline (simplified from core Pipeline) ────────────────────────


class ImagePipeline:
    """Composable operator chain with static key validation."""

    def __init__(self) -> None:
        self._ops: list[ImageOp] = []

    def pipe(self, *ops: ImageOp) -> ImagePipeline:
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
        return f"ImagePipeline({names})"

    def __len__(self) -> int:
        return len(self._ops)


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
        grayscale,
        invert,
        resize,
    )


_register_builtins()


# ── Parser ───────────────────────────────────────────────────────────────


def parse_operators(spec: str, sep: str = ",") -> list[ImageOp]:
    """Parse operator spec string into instantiated operators.

    Format: "grayscale,clahe:clip_limit=3.0,denoise:strength=10;method=bilateral"

    Args:
        spec: Operator specification string.
        sep: Token separator. Defaults to comma; use "|" for MapFramesOp.
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


def _make_op(name: str, kwargs: dict) -> ImageOp:
    if name not in OPERATORS:
        raise ValueError(f"Unknown operator: '{name}'. Available: {list(OPERATORS.keys())}")
    return OPERATORS[name](**kwargs)


# ── Preprocessing Runner ─────────────────────────────────────────────────


def run_preprocessing(file_path: str, ops: list[ImageOp]) -> str:
    """Load image, run operator pipeline, write temp file.

    Returns the original file_path if ops is empty,
    otherwise a temp PNG path (caller must clean up).

    Prefers cv2 for loading/saving; falls back to Pillow if unavailable.
    """
    if not ops:
        return file_path

    try:
        import cv2

        img = cv2.imread(file_path)
        color_space = "bgr"
    except ImportError:
        import numpy as np
        from PIL import Image

        img = np.array(Image.open(file_path))
        color_space = "rgb"

    if img is None:
        raise ValueError(f"Failed to load image: {file_path}")

    h, w = img.shape[:2]
    ctx = {
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

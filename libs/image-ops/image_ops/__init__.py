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

import copy
import logging
import os
import re
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol, runtime_checkable

import numpy as np

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
    """Composable operator chain with static key validation.

    RxJS-style creation + pipe + execute:
        ImagePipeline.from_file("scan.png").pipe(GrayscaleOp(), ClaheOp()).execute()
        ImagePipeline.of(img_array).pipe(ResizeOp(width=800)).execute()
    """

    def __init__(self) -> None:
        self._ops: list[ImageOp] = []
        self._initial_ctx: dict[str, Any] | None = None

    # ── Creation (RxJS: of / from) ───────────────────────────────────────

    @classmethod
    def of(cls, image: np.ndarray, **extra) -> ImagePipeline:
        """of() — wrap in-memory image array into a pipeline."""
        p = cls()
        h, w = image.shape[:2]
        p._initial_ctx = {
            "image": image,
            "width": w,
            "height": h,
            "color_space": extra.pop("color_space", "rgb"),
            **extra,
        }
        return p

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
        p = cls()
        p._initial_ctx = {
            "image": img,
            "width": w,
            "height": h,
            "color_space": color_space,
            "image_path": str(path),
            "source_path": str(path),
            **extra,
        }
        return p

    # ── Operators ────────────────────────────────────────────────────────

    def pipe(self, *ops: ImageOp) -> ImagePipeline:
        self._ops.extend(ops)
        return self

    def compile(self, initial_keys: set[str] | None = None) -> list[str]:
        available = set(initial_keys) if initial_keys else set()
        if self._initial_ctx:
            available |= set(self._initial_ctx.keys())
        missing: list[str] = []
        for op in self._ops:
            for key in op.input_keys:
                if key not in available:
                    missing.append(f"{op.name}: requires '{key}'")
            for key in op.output_keys:
                available.add(key)
        return missing

    def execute(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = ctx if ctx is not None else (self._initial_ctx or {})
        for op in self._ops:
            ctx = op(ctx)
        return ctx

    def __repr__(self) -> str:
        source = ""
        if self._initial_ctx and "source_path" in self._initial_ctx:
            source = f"from({self._initial_ctx['source_path']}) -> "
        elif self._initial_ctx:
            w = self._initial_ctx.get("width", "?")
            h = self._initial_ctx.get("height", "?")
            source = f"of({w}x{h}) -> "
        names = " -> ".join(op.name for op in self._ops)
        return f"ImagePipeline({source}{names})"

    def __len__(self) -> int:
        return len(self._ops)


# ── Combinators (shared with audio_ops — same ctx dict protocol) ────────


class ParallelOp:
    """Fork ctx to multiple ops, execute concurrently, merge results."""

    def __init__(self, *ops: ImageOp, name: str | None = None):
        if len(ops) < 2:
            raise ValueError("ParallelOp requires at least 2 operators")
        self._ops = ops
        self._name = name or f"parallel({'+'.join(op.name for op in ops)})"

    @property
    def name(self) -> str:
        return self._name

    @property
    def input_keys(self) -> tuple[str, ...]:
        return tuple(sorted({k for op in self._ops for k in op.input_keys}))

    @property
    def output_keys(self) -> tuple[str, ...]:
        return tuple(sorted({k for op in self._ops for k in op.output_keys}))

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        with ThreadPoolExecutor(max_workers=len(self._ops)) as pool:
            futures = [pool.submit(op, copy.deepcopy(ctx)) for op in self._ops]
            results = [f.result() for f in futures]
        merged = dict(ctx)
        for result in results:
            for key in result:
                if key not in ctx or key in {k for op in self._ops for k in op.output_keys}:
                    merged[key] = result[key]
        return merged

    def __repr__(self) -> str:
        return self._name


class TapOp:
    """Side-effect observer — runs callback without modifying ctx."""

    name = "tap"
    input_keys: tuple[str, ...] = ()
    output_keys: tuple[str, ...] = ()

    def __init__(self, fn: Callable[[dict[str, Any]], None], name: str = "tap"):
        self._fn = fn
        self.name = name  # type: ignore[assignment]

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        self._fn(ctx)
        return ctx


class ConditionalOp:
    """Conditional branch — run then_op if predicate is true, else else_op."""

    def __init__(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        then_op: ImageOp,
        else_op: ImageOp | None = None,
        *,
        name: str = "conditional",
    ):
        self._predicate = predicate
        self._then_op = then_op
        self._else_op = else_op
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def input_keys(self) -> tuple[str, ...]:
        keys: set[str] = set(self._then_op.input_keys)
        if self._else_op:
            keys |= set(self._else_op.input_keys)
        return tuple(sorted(keys))

    @property
    def output_keys(self) -> tuple[str, ...]:
        keys: set[str] = set(self._then_op.output_keys)
        if self._else_op:
            keys |= set(self._else_op.output_keys)
        return tuple(sorted(keys))

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        if self._predicate(ctx):
            return self._then_op(ctx)
        elif self._else_op:
            return self._else_op(ctx)
        return ctx


class CatchOp:
    """Error recovery wrapper — catches exceptions and runs fallback."""

    def __init__(
        self,
        op: ImageOp,
        *,
        fallback_ctx: dict[str, Any] | None = None,
        handler: Callable[[dict, Exception], dict] | None = None,
        name: str | None = None,
    ):
        self._op = op
        self._fallback = fallback_ctx
        self._handler = handler
        self._name = name or f"catch({op.name})"

    @property
    def name(self) -> str:
        return self._name

    @property
    def input_keys(self) -> tuple[str, ...]:
        return self._op.input_keys

    @property
    def output_keys(self) -> tuple[str, ...]:
        return self._op.output_keys

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._op(ctx)
        except Exception as e:
            logger.warning("CatchOp: %s failed: %s", self._op.name, e)
            if self._handler:
                return self._handler(ctx, e)
            if self._fallback:
                return {**ctx, **self._fallback}
            return ctx


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

_PARALLEL_RE = re.compile(r"^\[(.+)]$")


def parse_operators(spec: str, sep: str = ",") -> list[ImageOp]:
    """Parse operator spec string into instantiated operators.

    Format: "grayscale,clahe:clip_limit=3.0,[denoise+deskew]"
    Parallel groups: [op1+op2] syntax.

    Args:
        spec: Operator specification string.
        sep: Token separator. Defaults to comma; use "|" for MapFramesOp.
    """
    ops = []
    for token in _split_top_level(spec, sep):
        token = token.strip()
        if not token:
            continue
        parallel_match = _PARALLEL_RE.match(token)
        if parallel_match:
            inner = parallel_match.group(1)
            sub_ops = [_parse_single(t.strip()) for t in inner.split("+") if t.strip()]
            ops.append(ParallelOp(*sub_ops))
        else:
            ops.append(_parse_single(token))
    return ops


def _split_top_level(spec: str, sep: str = ",") -> list[str]:
    """Split by sep, but respect [...] groups."""
    tokens = []
    depth = 0
    current: list[str] = []
    for ch in spec:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == sep and depth == 0:
            tokens.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def _parse_single(token: str) -> ImageOp:
    """Parse a single operator token like 'clahe:clip_limit=3.0'."""
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
        return _make_op(name.strip(), kwargs)
    return _make_op(token.strip(), {})


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

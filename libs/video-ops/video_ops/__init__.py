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

import copy
import logging
import os
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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
    """Composable operator chain with static key validation.

    RxJS-style creation + pipe + execute:
        VideoPipeline.from_file("vid.mp4").pipe(ProbeOp(), TrimOp(start=10)).execute()
    """

    def __init__(self) -> None:
        self._ops: list[VideoOp] = []
        self._initial_ctx: dict[str, Any] | None = None

    # ── Creation (RxJS: from) ────────────────────────────────────────────

    @classmethod
    def from_file(cls, path: str | Path, **extra) -> VideoPipeline:
        """from() — create pipeline from video file path."""
        p = cls()
        p._initial_ctx = {
            "video_path": str(path),
            "source_path": str(path),
            **extra,
        }
        return p

    # ── Operators ────────────────────────────────────────────────────────

    def pipe(self, *ops: VideoOp) -> VideoPipeline:
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
        names = " -> ".join(op.name for op in self._ops)
        return f"VideoPipeline({source}{names})"

    def __len__(self) -> int:
        return len(self._ops)


# ── Combinators (shared with audio_ops/image_ops — same ctx dict protocol) ──


class ParallelOp:
    """Fork ctx to multiple ops, execute concurrently, merge results."""

    def __init__(self, *ops: VideoOp, name: str | None = None):
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
        then_op: VideoOp,
        else_op: VideoOp | None = None,
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
        op: VideoOp,
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

_PARALLEL_RE = re.compile(r"^\[(.+)]$")


def parse_operators(spec: str, sep: str = ",") -> list[VideoOp]:
    """Parse operator spec string into instantiated operators.

    Format: "probe,extract-frames:fps=2,[thumbnail+detect-scenes]"
    Parallel groups: [op1+op2] syntax.
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


def _parse_single(token: str) -> VideoOp:
    """Parse a single operator token like 'trim:start=10;end=30'."""
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

"""Audio operators — shared across STT, TTS, voice-gateway, and RVC.

RxJS-inspired Operator Protocol — same interface as core/src/shared/reactive.py
but self-contained for station isolation.

Usage:
    from audio_ops import parse_operators, run_preprocessing
    ops = parse_operators("denoise,vad-trim:threshold=0.3,normalize")
    processed_path = run_preprocessing("/path/to/audio.wav", ops)

    from audio_ops.diarize import DiarizeOp
    from audio_ops.extract_audio import ExtractAudioOp
    from audio_ops.merge import MergeOp, find_speaker

Model directory resolution order:
    1. ``model_dir`` kwarg passed to the operator constructor
    2. ``WORKSHOP_AUDIO_MODELS`` environment variable
    3. ``~/workshop/stations/stt/models/`` (legacy default)
"""

from __future__ import annotations

import copy
import logging
import os
import re
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


# ── Default model directory ────────────────────────────────────────────────


def _default_model_dir() -> Path:
    """Resolve the default audio models directory.

    Resolution order:
    1. WORKSHOP_AUDIO_MODELS env var
    2. ~/workshop/stations/stt/models/ (legacy fallback)
    """
    env_val = os.environ.get("WORKSHOP_AUDIO_MODELS")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return Path.home() / "workshop" / "stations" / "stt" / "models"


# ── AudioOp Protocol (mirrors core/src/shared/reactive.Operator) ──────────


@runtime_checkable
class AudioOp(Protocol):
    """Pure function audio transform — the GCF of all preprocessing stages.

    Sync __call__ because all audio operators are CPU-bound (no async I/O).
    This avoids event loop conflicts when called from FastAPI via to_thread().
    """

    @property
    def name(self) -> str: ...

    @property
    def input_keys(self) -> tuple[str, ...]: ...

    @property
    def output_keys(self) -> tuple[str, ...]: ...

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]: ...


# ── AudioPipeline (simplified from core Pipeline) ─────────────────────────


class AudioPipeline:
    """Composable operator chain with static key validation.

    RxJS-style creation + pipe + execute:
        AudioPipeline.from_file("a.wav").pipe(DenoiseOp(), EmotionOp()).execute()
        AudioPipeline.of(audio, sr).pipe(NormalizeOp()).execute()
    """

    def __init__(self) -> None:
        self._ops: list[AudioOp] = []
        self._initial_ctx: dict[str, Any] | None = None

    # ── Creation (RxJS: of / from) ───────────────────────────────────────

    @classmethod
    def of(cls, audio: np.ndarray, sample_rate: int, **extra) -> AudioPipeline:
        """of() — wrap in-memory audio array into a pipeline."""
        p = cls()
        if audio.ndim > 1:
            audio = audio[:, 0]
        p._initial_ctx = {
            "audio": audio,
            "sample_rate": int(sample_rate),
            **extra,
        }
        return p

    @classmethod
    def from_file(cls, path: str | Path, **extra) -> AudioPipeline:
        """from() — read audio file into a pipeline."""
        path = str(path)
        audio, sr = sf.read(path, dtype="float32")
        if audio.ndim > 1:
            audio = audio[:, 0]
        p = cls()
        p._initial_ctx = {
            "audio": audio,
            "sample_rate": int(sr),
            "source_path": path,
            **extra,
        }
        return p

    # ── Operators ────────────────────────────────────────────────────────

    def pipe(self, *ops: AudioOp) -> AudioPipeline:
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
            sr = self._initial_ctx.get("sample_rate", "?")
            source = f"of(sr={sr}) -> "
        names = " -> ".join(op.name for op in self._ops)
        return f"AudioPipeline({source}{names})"

    def __len__(self) -> int:
        return len(self._ops)


# ── ParallelOp (sync fork+merge, mirrors core/shared/reactive.ParallelOp) ──


class ParallelOp:
    """Fork ctx to multiple ops, execute concurrently, merge results.

    Sync equivalent of core reactive's async ParallelOp.
    Uses ThreadPoolExecutor because numpy/ONNX ops release the GIL.

    Usage:
        pipeline.pipe(ParallelOp(DiarizeOp(), EmotionOp()))
        # or via spec: "denoise,[diarize+emotion]"
    """

    def __init__(self, *ops: AudioOp, name: str | None = None):
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


# ── TapOp (RxJS: tap — side-effect without modifying ctx) ────────────────


class TapOp:
    """Side-effect observer — runs a callback without modifying the ctx.

    RxJS equivalent: tap(x => console.log(x))

    Usage:
        pipeline.pipe(
            DenoiseOp(),
            TapOp(lambda ctx: logger.info("after denoise: %s", ctx.keys())),
            EmotionOp(),
        )
    """

    name = "tap"
    input_keys: tuple[str, ...] = ()
    output_keys: tuple[str, ...] = ()

    def __init__(self, fn: Callable[[dict[str, Any]], None], name: str = "tap"):
        self._fn = fn
        self.name = name  # type: ignore[assignment]

    def __call__(self, ctx: dict[str, Any]) -> dict[str, Any]:
        self._fn(ctx)
        return ctx

    def __repr__(self) -> str:
        return self.name


# ── ConditionalOp (RxJS: iif / filter — branch on predicate) ────────────


class ConditionalOp:
    """Conditional branch — run then_op if predicate is true, else else_op.

    RxJS equivalent: iif(() => condition, thenObs$, elseObs$)

    Usage:
        ConditionalOp(
            lambda ctx: "diarization_segments" in ctx,
            then_op=EmotionOp(),   # per-segment
            else_op=NormalizeOp(), # fallback
        )
    """

    def __init__(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        then_op: AudioOp,
        else_op: AudioOp | None = None,
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

    def __repr__(self) -> str:
        then_name = self._then_op.name
        else_name = self._else_op.name if self._else_op else "pass"
        return f"{self._name}({then_name}|{else_name})"


# ── CatchOp (RxJS: catchError — error recovery) ─────────────────────────


class CatchOp:
    """Error recovery wrapper — catches exceptions and runs fallback.

    RxJS equivalent: catchError(err => of(fallbackValue))

    Usage:
        CatchOp(EmotionOp(), fallback_ctx={"emotions": []})
        CatchOp(EmotionOp(), handler=lambda ctx, e: {**ctx, "emotions": []})
    """

    def __init__(
        self,
        op: AudioOp,
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

    def __repr__(self) -> str:
        return self._name


# ── Registry ──────────────────────────────────────────────────────────────

OPERATORS: dict[str, type] = {}


def register(name: str):
    """Decorator to register an operator class."""

    def wrapper(cls):
        OPERATORS[name] = cls
        return cls

    return wrapper


# Import operators to trigger registration
def _register_builtins():
    from . import denoise, diarize, emotion, extract_audio, merge, normalize, vad_trim  # noqa: F401


_register_builtins()


# ── Parser ────────────────────────────────────────────────────────────────

# Regex for parallel group: [op1+op2+op3]
_PARALLEL_RE = re.compile(r"^\[(.+)]$")


def parse_operators(spec: str) -> list[AudioOp]:
    """Parse operator spec string into instantiated operators.

    Format: "denoise,vad-trim:threshold=0.3,normalize:target_db=-6,[diarize+emotion]"

    Parallel groups use [op1+op2] syntax — executes ops concurrently via ParallelOp.
    """
    ops = []
    for token in _split_top_level(spec):
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


def _split_top_level(spec: str) -> list[str]:
    """Split by comma, but respect [...] groups."""
    tokens = []
    depth = 0
    current = []
    for ch in spec:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            tokens.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def _parse_single(token: str) -> AudioOp:
    """Parse a single operator token like 'normalize:target_db=-6'."""
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


def _make_op(name: str, kwargs: dict) -> AudioOp:
    if name not in OPERATORS:
        raise ValueError(f"Unknown operator: '{name}'. Available: {list(OPERATORS.keys())}")
    return OPERATORS[name](**kwargs)


# ── Preprocessing Runner ──────────────────────────────────────────────────


def run_preprocessing(file_path: str, ops: list[AudioOp]) -> str:
    """Load audio, run operator pipeline, write temp file.

    Returns the original file_path if ops is empty,
    otherwise a temp WAV path (caller must clean up).
    """
    if not ops:
        return file_path

    audio, sample_rate = sf.read(file_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio[:, 0]  # mono

    ctx = {
        "audio": audio,
        "sample_rate": int(sample_rate),
        "source_path": file_path,
    }

    pipeline = AudioPipeline().pipe(*ops)
    missing = pipeline.compile(set(ctx.keys()))
    if missing:
        raise ValueError(f"Pipeline key validation failed: {missing}")

    ctx = pipeline.execute(ctx)

    processed_audio = ctx["audio"]
    processed_sr = ctx["sample_rate"]

    fd, tmp_path = tempfile.mkstemp(suffix=".wav", prefix="audio-op-")
    os.close(fd)
    sf.write(tmp_path, processed_audio, processed_sr)

    orig_dur = len(audio) / sample_rate
    proc_dur = len(processed_audio) / processed_sr
    logger.info("Preprocessing: %s (%.1fs -> %.1fs)", pipeline, orig_dur, proc_dur)

    return tmp_path


# ── Analysis convenience re-exports ──────────────────────────────────────

from .merge import consolidate_segments, find_speaker, format_time, to_markdown  # noqa: E402, F401

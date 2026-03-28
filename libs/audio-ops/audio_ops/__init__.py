"""Audio preprocessing operators — shared across STT, TTS, voice-gateway, and RVC.

RxJS-inspired Operator Protocol — same interface as core/src/shared/reactive.py
but self-contained for station isolation.

Usage:
    from audio_ops import parse_operators, run_preprocessing
    ops = parse_operators("denoise,vad-trim:threshold=0.3,normalize")
    processed_path = run_preprocessing("/path/to/audio.wav", ops)

Model directory resolution order:
    1. ``model_dir`` kwarg passed to the operator constructor
    2. ``WORKSHOP_AUDIO_MODELS`` environment variable
    3. ``~/workshop/stations/stt/models/`` (legacy default)
"""

from __future__ import annotations

import logging
import os
import tempfile
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
    """Composable operator chain with static key validation."""

    def __init__(self) -> None:
        self._ops: list[AudioOp] = []

    def pipe(self, *ops: AudioOp) -> AudioPipeline:
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
        return f"AudioPipeline({names})"

    def __len__(self) -> int:
        return len(self._ops)


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
    from . import denoise, normalize, vad_trim  # noqa: F401


_register_builtins()


# ── Parser ────────────────────────────────────────────────────────────────


def parse_operators(spec: str) -> list[AudioOp]:
    """Parse operator spec string into instantiated operators.

    Format: "denoise,vad-trim:threshold=0.3;min_silence_duration=0.8,normalize:target_db=-6"
    """
    ops = []
    for token in spec.split(","):
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

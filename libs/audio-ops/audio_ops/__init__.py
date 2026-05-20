"""Audio operators — shared across STT, TTS, voice-gateway, and RVC.

Inherits from ops_core.BasePipe (unified batch + streaming).

Usage:
    # Batch
    AudioPipe.from_file("a.wav").pipe(DenoiseOp(), EmotionOp()).execute()
    AudioPipe.of(audio, sr).pipe(NormalizeOp()).execute()

    # Streaming
    AudioPipe.from_chunks(ws_gen, sr=16000).pipe(
        BufferCount(16000, merge_key="audio"),
        EmotionOp(),
    ).subscribe(callback)

Model directory resolution order:
    1. ``model_dir`` kwarg passed to the operator constructor
    2. ``WORKSHOP_AUDIO_MODELS`` environment variable
    3. ``~/workshop/stations/stt/models/`` (legacy default)
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import soundfile as sf
from ops_core import (  # noqa: F401 — re-export for backward compat
    # Base
    BasePipe,
    # Stream combinators
    BufferCount,
    BufferTime,
    # Batch combinators
    CatchOp,
    ConditionalOp,
    Debounce,
    DelayOp,
    DistinctUntilChanged,
    Filter,
    FinalizeOp,
    ParallelOp,
    RetryOp,
    Scan,
    Skip,
    Take,
    TapOp,
    Throttle,
    TimeoutOp,
    Window,
    # Parser
    parse_spec,
)
from ops_core import Op as AudioOp

logger = logging.getLogger(__name__)


# ── Default model directory ────────────────────────────────────────────────


def _default_model_dir() -> Path:
    env_val = os.environ.get("WORKSHOP_AUDIO_MODELS")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return Path.home() / "workshop" / "stations" / "stt" / "models"


# ── AudioPipe ────────────────────────────────────────────────────────────


class AudioPipe(BasePipe):
    """Unified audio pipe — batch or streaming, decided by source."""

    # ── Batch sources ────────────────────────────────────────────────

    @classmethod
    def of(cls, audio: np.ndarray, sample_rate: int, **extra) -> AudioPipe:
        """of() — wrap in-memory audio array."""
        if audio.ndim > 1:
            audio = audio[:, 0]
        return cls._create_batch(
            {
                "audio": audio,
                "sample_rate": int(sample_rate),
                **extra,
            }
        )

    @classmethod
    def from_file(cls, path: str | Path, **extra) -> AudioPipe:
        """from() — read audio file."""
        path = str(path)
        audio, sr = sf.read(path, dtype="float32")
        if audio.ndim > 1:
            audio = audio[:, 0]
        return cls._create_batch(
            {
                "audio": audio,
                "sample_rate": int(sr),
                "source_path": path,
                **extra,
            }
        )

    # ── Streaming sources ────────────────────────────────────────────

    @classmethod
    def from_chunks(
        cls,
        source: Iterable,
        sample_rate: int = 16000,
    ) -> AudioPipe:
        """from_chunks() — stream from audio chunk generator."""

        def _wrap():
            for item in source:
                if isinstance(item, dict):
                    yield item
                else:
                    yield {"audio": item, "sample_rate": sample_rate}

        return cls._create_stream(_wrap())

    # ── Repr ─────────────────────────────────────────────────────────

    def _repr_source(self) -> str:
        if self._initial_ctx and "source_path" in self._initial_ctx:
            return f"from({self._initial_ctx['source_path']}) -> "
        elif self._initial_ctx:
            sr = self._initial_ctx.get("sample_rate", "?")
            return f"of(sr={sr}) -> "
        elif self._is_streaming:
            return "chunks -> "
        return ""


# Backward compat


# ── Registry ──────────────────────────────────────────────────────────────

OPERATORS: dict[str, type] = {}


def register(name: str):
    def wrapper(cls):
        OPERATORS[name] = cls
        return cls

    return wrapper


def _register_builtins():
    from . import (  # noqa: F401
        analyze,
        denoise,
        diarize,
        emotion,
        extract_audio,
        merge,
        normalize,
        vad_trim,
    )
    # speaker_similarity + visualize sit behind optional extras
    # (resemblyzer / librosa+matplotlib). Import lazily so the core library
    # remains usable without those deps installed.
    for modname in ("speaker_similarity", "visualize"):
        try:
            __import__(f"{__name__}.{modname}")
        except ImportError as e:
            logger.debug("optional op '%s' not registered: %s", modname, e)


_register_builtins()


# ── Parser ────────────────────────────────────────────────────────────────


def _make_op(name: str, kwargs: dict) -> AudioOp:
    if name not in OPERATORS:
        raise ValueError(f"Unknown operator: '{name}'. Available: {list(OPERATORS.keys())}")
    return OPERATORS[name](**kwargs)


def parse_operators(spec: str) -> list[AudioOp]:
    return parse_spec(spec, _make_op)


# ── Preprocessing Runner ──────────────────────────────────────────────────


def run_preprocessing(file_path: str, ops: list[AudioOp]) -> str:
    if not ops:
        return file_path

    audio, sample_rate = sf.read(file_path, dtype="float32")
    if audio.ndim > 1:
        audio = audio[:, 0]

    ctx = {"audio": audio, "sample_rate": int(sample_rate), "source_path": file_path}

    pipeline = AudioPipe().pipe(*ops)
    missing = pipeline.compile(set(ctx.keys()))
    if missing:
        raise ValueError(f"Pipeline key validation failed: {missing}")

    ctx = pipeline.execute(ctx)

    fd, tmp_path = tempfile.mkstemp(suffix=".wav", prefix="audio-op-")
    os.close(fd)
    sf.write(tmp_path, ctx["audio"], ctx["sample_rate"])

    return tmp_path


# ── Convenience re-exports ───────────────────────────────────────────────

from .merge import consolidate_segments, find_speaker, format_time, to_markdown  # noqa: E402, F401
from .pipeline import AudioSegment, build_audio_track  # noqa: E402, F401

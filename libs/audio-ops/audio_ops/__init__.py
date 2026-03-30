"""Audio operators — shared across STT, TTS, voice-gateway, and RVC.

Inherits from ops_core (shared protocol + combinators).

Usage:
    from audio_ops import parse_operators, run_preprocessing
    ops = parse_operators("denoise,vad-trim:threshold=0.3,normalize")
    processed_path = run_preprocessing("/path/to/audio.wav", ops)

    from audio_ops import AudioPipeline, ParallelOp, TapOp
    AudioPipeline.from_file("a.wav").pipe(DenoiseOp(), EmotionOp()).execute()

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

import numpy as np
import soundfile as sf
from ops_core import (  # noqa: F401 — re-export for backward compat
    BasePipeline,
    CatchOp,
    ConditionalOp,
    ParallelOp,
    TapOp,
    parse_spec,
)
from ops_core import (
    Op as AudioOp,
)

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


# ── AudioPipeline ────────────────────────────────────────────────────────


class AudioPipeline(BasePipeline):
    """Audio-specific pipeline with of(array, sr) and from_file(path)."""

    @classmethod
    def of(cls, audio: np.ndarray, sample_rate: int, **extra) -> AudioPipeline:
        """of() — wrap in-memory audio array into a pipeline."""
        if audio.ndim > 1:
            audio = audio[:, 0]
        return cls._create(
            {
                "audio": audio,
                "sample_rate": int(sample_rate),
                **extra,
            }
        )

    @classmethod
    def from_file(cls, path: str | Path, **extra) -> AudioPipeline:
        """from() — read audio file into a pipeline."""
        path = str(path)
        audio, sr = sf.read(path, dtype="float32")
        if audio.ndim > 1:
            audio = audio[:, 0]
        return cls._create(
            {
                "audio": audio,
                "sample_rate": int(sr),
                "source_path": path,
                **extra,
            }
        )

    def _repr_source(self) -> str:
        if self._initial_ctx and "source_path" in self._initial_ctx:
            return f"from({self._initial_ctx['source_path']}) -> "
        elif self._initial_ctx:
            sr = self._initial_ctx.get("sample_rate", "?")
            return f"of(sr={sr}) -> "
        return ""


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


def _make_op(name: str, kwargs: dict) -> AudioOp:
    if name not in OPERATORS:
        raise ValueError(f"Unknown operator: '{name}'. Available: {list(OPERATORS.keys())}")
    return OPERATORS[name](**kwargs)


def parse_operators(spec: str) -> list[AudioOp]:
    """Parse operator spec string with [a+b] parallel support."""
    return parse_spec(spec, _make_op)


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

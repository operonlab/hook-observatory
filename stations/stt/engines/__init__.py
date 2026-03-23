"""STT Engine Registry -- Strategy pattern for speech-to-text backends."""

from __future__ import annotations

from typing import Protocol


class STTEngine(Protocol):
    """Base protocol for STT engines."""

    name: str

    def transcribe(self, file_path: str, language: str = "zh-TW") -> dict:
        """Transcribe audio file and return result dict.

        Returns:
            {"text": str, "language": str, "segments": list, "engine": str}
        """
        ...


ENGINES: dict[str, STTEngine] = {}


def register(name: str):
    """Decorator to register an engine implementation."""

    def decorator(cls):
        ENGINES[name] = cls()
        return cls

    return decorator


def get_engine(name: str = "apple") -> STTEngine:
    """Get engine by name. Defaults to apple."""
    if name not in ENGINES:
        available = list(ENGINES.keys())
        raise ValueError(f"Unknown STT engine: {name}. Available: {available}")
    return ENGINES[name]


# Auto-import engines to trigger registration
from . import apple as _apple  # noqa: F401, E402
from . import mlx_whisper as _mlx_whisper  # noqa: F401, E402
from . import openai_api as _openai_api  # noqa: F401, E402
from . import qwen3_asr as _qwen3_asr  # noqa: F401, E402

"""TTS Engine Registry — Strategy pattern for text-to-speech backends."""

from __future__ import annotations

from typing import Protocol


class TTSEngine(Protocol):
    """Base protocol for TTS engines."""

    name: str

    def synthesize(
        self,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        output_path: str | None = None,
    ) -> dict:
        """Synthesize speech from text.

        Returns:
            {"audio_path": str, "duration": float, "sample_rate": int, "engine": str}
        """
        ...

    def list_voices(self) -> list[dict]:
        """List available voices.

        Returns:
            [{"id": str, "name": str, "language": str}]
        """
        ...


ENGINES: dict[str, TTSEngine] = {}


def register(name: str):
    """Decorator to register an engine implementation."""

    def decorator(cls):
        ENGINES[name] = cls()
        return cls

    return decorator


def get_engine(name: str = "apple") -> TTSEngine:
    """Get engine by name. Defaults to apple."""
    if name not in ENGINES:
        available = list(ENGINES.keys())
        raise ValueError(f"Unknown TTS engine: {name}. Available: {available}")
    return ENGINES[name]


# Auto-import engines to trigger registration
from . import apple as _apple  # noqa: F401, E402
from . import elevenlabs_api as _elevenlabs  # noqa: F401, E402
from . import qwen3_tts as _qwen3_tts  # noqa: F401, E402

# Kokoro: optional — requires misaki+phonemizer+espeak (dependency chain unstable)
try:
    from . import kokoro as _kokoro  # noqa: F401
except ImportError:
    pass

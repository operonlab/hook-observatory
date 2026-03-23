"""Vision Engine Registry — Strategy pattern for visual analysis backends."""

from __future__ import annotations

from typing import Protocol


class VisionEngine(Protocol):
    """Base protocol for vision engines."""

    name: str

    def analyze(
        self,
        file_path: str,
        task: str = "describe",
        prompt: str | None = None,
    ) -> dict:
        """Analyze image and return results.

        Args:
            file_path: Path to image file
            task: "describe" | "detect" | "classify" | "qa" | "barcode" | "face"
            prompt: Free-form question (required for task="qa")

        Returns:
            {"result": str|list, "engine": str, "task": str}
        """
        ...


ENGINES: dict[str, VisionEngine] = {}


def register(name: str):
    """Decorator to register an engine implementation."""

    def decorator(cls):
        ENGINES[name] = cls()
        return cls

    return decorator


def get_engine(name: str = "apple") -> VisionEngine:
    """Get engine by name. Defaults to apple."""
    if name not in ENGINES:
        available = list(ENGINES.keys())
        raise ValueError(f"Unknown vision engine: {name}. Available: {available}")
    return ENGINES[name]


# Auto-import engines to trigger registration
from . import apple as _apple  # noqa: F401, E402
from . import claude as _claude  # noqa: F401, E402
from . import gemini as _gemini  # noqa: F401, E402
from . import minicpm as _minicpm  # noqa: F401, E402
from . import smolvlm as _smolvlm  # noqa: F401, E402
from . import yolo as _yolo  # noqa: F401, E402

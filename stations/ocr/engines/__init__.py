"""OCR Engine Registry — Strategy pattern for text extraction backends."""

from __future__ import annotations

from typing import Protocol


class OCREngine(Protocol):
    """Base protocol for OCR engines."""

    name: str

    def extract(self, file_path: str, languages: list[str] | None = None) -> dict:
        """Extract text from image or PDF.

        Returns:
            {"text": str, "blocks": list, "languages": list, "engine": str}
        """
        ...


ENGINES: dict[str, OCREngine] = {}


def register(name: str):
    """Decorator to register an engine implementation."""

    def decorator(cls):
        ENGINES[name] = cls()
        return cls

    return decorator


def get_engine(name: str = "apple") -> OCREngine:
    """Get engine by name. Defaults to apple."""
    if name not in ENGINES:
        available = list(ENGINES.keys())
        raise ValueError(f"Unknown OCR engine: {name}. Available: {available}")
    return ENGINES[name]


# Auto-import engines to trigger registration
from . import apple as _apple  # noqa: F401, E402
from . import claude as _claude  # noqa: F401, E402
from . import gemini as _gemini  # noqa: F401, E402
from . import paddle as _paddle  # noqa: F401, E402
from . import tesseract as _tesseract  # noqa: F401, E402

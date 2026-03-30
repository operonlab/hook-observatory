"""TTS Engine Registry — Strategy pattern for text-to-speech backends.

Device capability detection:
- MLX engines (qwen3-tts, kokoro): only load on Apple Silicon
- Torch-MPS engines (f5-tts): only load when torch + MPS available
- Torch-CUDA engines (cosyvoice, gpt-sovits): only load when torch + CUDA available
- Subprocess bridges (index-tts): always register, fail gracefully at runtime
"""

from __future__ import annotations

import logging
import platform
from typing import Protocol

logger = logging.getLogger(__name__)


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

# --- Device capability detection (checked once at import) ---

_HAS_MLX = False
_HAS_TORCH_MPS = False
_HAS_TORCH_CUDA = False

# MLX: Apple Silicon only
if platform.machine() == "arm64" and platform.system() == "Darwin":
    try:
        import mlx.core  # noqa: F401

        _HAS_MLX = True
    except ImportError:
        pass

# Torch: check MPS and CUDA
try:
    import torch

    _HAS_TORCH_MPS = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    _HAS_TORCH_CUDA = torch.cuda.is_available()
except ImportError:
    pass

# Engines that perform best with Simplified Chinese input (all mainland China models)
_SIMPLIFIED_CHINESE_ENGINES = {"f5-tts", "index-tts", "cosyvoice", "gpt-sovits", "qwen3-tts"}

_t2s = None


def to_simplified(text: str) -> str:
    """Convert Traditional Chinese to Simplified for mainland TTS engines."""
    global _t2s
    if _t2s is None:
        try:
            from opencc import OpenCC

            _t2s = OpenCC("t2s")
        except ImportError:
            return text
    return _t2s.convert(text)


def register(name: str):
    """Decorator to register an engine implementation.

    Wraps synthesize() to auto-run AnalyzeOp on output audio.
    """

    def decorator(cls):
        original_synthesize = cls.synthesize

        def _wrapped_synthesize(self, *args, **kwargs):
            result = original_synthesize(self, *args, **kwargs)
            return _post_synthesize_analyze(result, name)

        cls.synthesize = _wrapped_synthesize
        ENGINES[name] = cls()
        return cls

    return decorator


def get_engine(name: str = "apple") -> TTSEngine:
    """Get engine by name. Defaults to apple."""
    if name not in ENGINES:
        available = list(ENGINES.keys())
        raise ValueError(f"Unknown TTS engine: {name}. Available: {available}")
    return ENGINES[name]


def _post_synthesize_analyze(result: dict, engine_name: str) -> dict:
    """Run AnalyzeOp on synthesize output. Adds analysis to result dict."""
    audio_path = result.get("audio_path")
    if not audio_path or "error" in result:
        return result
    try:
        from audio_ops import OPERATORS, AudioPipe

        AnalyzeOp = OPERATORS.get("analyze")
        if AnalyzeOp is None:
            return result
        ctx = (
            AudioPipe.from_file(audio_path)
            .pipe(AnalyzeOp(generate_png=False, label=engine_name))
            .execute()
        )
        result["analysis_pass"] = ctx.get("analysis_pass", True)
        result["analysis_issues"] = ctx.get("analysis_issues", [])
        if not result["analysis_pass"]:
            issues = ", ".join(result["analysis_issues"][:3])
            logger.warning("TTS output FAILED quality check [%s]: %s", engine_name, issues)
    except Exception:
        pass  # audio-ops not installed — skip silently
    return result


# ── Always-available engines ──
from . import apple as _apple  # noqa: F401, E402
from . import elevenlabs_api as _elevenlabs  # noqa: F401, E402

# ── MLX engines (Apple Silicon only) ──
if _HAS_MLX:
    from . import qwen3_tts as _qwen3_tts  # noqa: F401

    try:
        from . import kokoro as _kokoro  # noqa: F401
    except ImportError:
        pass
else:
    logger.info("MLX not available — skipping qwen3-tts, kokoro")

# ── Torch-MPS engines (Mac with MPS) ──
if _HAS_TORCH_MPS or _HAS_TORCH_CUDA:
    try:
        from . import f5_tts as _f5_tts  # noqa: F401
    except ImportError:
        pass
else:
    logger.info("No torch GPU (MPS/CUDA) — skipping f5-tts")

# ── Torch-CUDA engines (GPU server only) ──
if _HAS_TORCH_CUDA:
    try:
        from . import cosyvoice as _cosyvoice  # noqa: F401
    except ImportError:
        pass
else:
    logger.info("No CUDA — skipping cosyvoice (MPS incompatible)")

# ── Subprocess bridge engines (always register, runtime check) ──
try:
    from . import index_tts as _index_tts  # noqa: F401
except ImportError:
    pass

try:
    from . import gpt_sovits as _gpt_sovits  # noqa: F401
except ImportError:
    pass

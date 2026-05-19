"""v2 engine registry — 6 個 v3 系列 engine 的工廠 + lazy registration.

與 engines/__init__.py 的 v1 registry 並存：
- v1 (ENGINES dict): edge / apple / elevenlabs / kokoro / f5-tts / gpt-sovits / mlx-qwen3-tts ...
- v2 (V2_ENGINES dict): cosyvoice_v3_native / cosyvoice_v3_vllm /
                        indextts2_base / indextts2_jmica / vibevoice / qwen3tts_gpu

v2 engine 透過 subprocess bridge 跑在 win-gpu，Mac 端 import 不會 load 模型，
但 healthcheck() 會回 false（python 路徑不存在）。
"""

from __future__ import annotations

import logging

from .base_v2 import TTSEngineV2
from .cosyvoice_v3 import CosyVoiceV3NativeEngine, CosyVoiceV3VllmEngine
from .indextts2 import IndexTTS2BaseEngine, IndexTTS2JmicaEngine
from .qwen3tts_gpu import Qwen3TTSGpuEngine
from .vibevoice import VibeVoiceEngine
# lifecycle lives at stations/tts/lifecycle.py (sibling of engines/), so the
# parent dir is expected on sys.path (main.py uses `from engines import ...`).
import sys as _sys
from pathlib import Path as _P

_parent = str(_P(__file__).resolve().parent.parent)
if _parent not in _sys.path:
    _sys.path.insert(0, _parent)

from lifecycle import MANAGER  # noqa: E402

logger = logging.getLogger(__name__)


def _build_registry() -> dict[str, TTSEngineV2]:
    """Instantiate each v2 engine (subprocess mode → cheap)."""
    registry: dict[str, TTSEngineV2] = {
        "cosyvoice_v3_native": CosyVoiceV3NativeEngine(),
        "cosyvoice_v3_vllm": CosyVoiceV3VllmEngine(),
        "indextts2_base": IndexTTS2BaseEngine(),
        "indextts2_jmica": IndexTTS2JmicaEngine(),
        "vibevoice": VibeVoiceEngine(),
        "qwen3tts_gpu": Qwen3TTSGpuEngine(),
    }
    for name, eng in registry.items():
        MANAGER.register(name, eng)
    return registry


V2_ENGINES: dict[str, TTSEngineV2] = _build_registry()


def get_v2_engine(name: str) -> TTSEngineV2:
    if name not in V2_ENGINES:
        raise ValueError(
            f"Unknown v2 engine: {name}. Available: {list(V2_ENGINES.keys())}"
        )
    return V2_ENGINES[name]


def list_v2_engines() -> list[dict]:
    """Return capability + health summary."""
    out = []
    for name, eng in V2_ENGINES.items():
        cap = eng.capability()
        health = eng.healthcheck()
        out.append({
            "name": name,
            "languages": cap.languages,
            "multi_speaker": cap.multi_speaker,
            "rtf_typical": cap.rtf_typical,
            "vram_mb": cap.vram_mb,
            "needs_wsl": cap.needs_wsl,
            "needs_gpu": cap.needs_gpu,
            "supported_outputs": [o.value for o in cap.supported_outputs],
            "sample_rate": cap.sample_rate,
            "notes": cap.notes,
            "healthy": health.get("ok", False),
            "health_detail": health,
        })
    return out

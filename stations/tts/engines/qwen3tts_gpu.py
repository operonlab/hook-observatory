"""Qwen3-TTS GPU engine — 0.6B-Base HuggingFace 版（WSL2）.

Repo: ~/qwen3tts_models/Qwen3-TTS-12Hz-0.6B-Base/
Venv: 共用 ~/.venvs/cosyvoice_vllm/

**注意命名**：避免跟既有 `stations/tts/engines/qwen3_tts.py`（mlx-audio Mac 版）撞名，
這個用 `qwen3tts_gpu` engine ID。同 family 不同實作。

特色：
- 中英日韓 4 種 native（少爺日語線之一）
- zero-shot 必填 ref_text
- 0.6B-Base 才是 zero-shot variant，0.6B-CustomVoice 不是（少爺記憶踩過）
"""

from __future__ import annotations

from .base_v2 import EngineCapability, OutputMode
from .subprocess_bridge import SubprocessEngine


class Qwen3TTSGpuEngine(SubprocessEngine):
    WSL_DISTRO = "Ubuntu"
    PYTHON = "/home/joneshong/.venvs/cosyvoice_vllm/bin/python3"
    RUNNER = "run_qwen3tts.py"
    CWD = "/home/joneshong"
    TIMEOUT_SEC = 180

    def _build_input(self, req):
        d = super()._build_input(req)
        d.update({
            "model_path": "/home/joneshong/qwen3tts_models/Qwen3-TTS-12Hz-0.6B-Base",
        })
        return d

    def capability(self) -> EngineCapability:
        return EngineCapability(
            name="qwen3tts_gpu",
            languages=["zh", "en", "ja", "ko"],
            multi_speaker=False,
            rtf_typical=1.19,
            vram_mb=3000,
            needs_wsl=True,
            needs_gpu=True,
            ref_duration_range=(3, 15),
            needs_ref_text=True,
            supported_outputs=[
                OutputMode.FILE, OutputMode.BUFFER, OutputMode.NUMPY,
                OutputMode.TENSOR, OutputMode.BASE64,
            ],
            sample_rate=24000,
            notes="WSL2 HF 版 0.6B-Base。中英日韓 native，zero-shot 必填 ref_text",
        )

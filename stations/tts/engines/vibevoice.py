"""VibeVoice 1.5B engine — multi-speaker / podcast TTS (WSL2).

Repo: ~/VibeVoice/ (community fork)
Model: ~/vibevoice_models/VibeVoice-1.5B/
Venv: 共用 ~/.venvs/cosyvoice_vllm/

特色：
- 真 streaming（VibeVoice 賣點）
- 多 speaker dialog（唯一 niche）
- **不支援 ja**（少爺記憶確認）

ref 需 3-30s，需 ref_text（多 speaker 場景每位 speaker 各一份 ref）。
"""

from __future__ import annotations

from .base_v2 import EngineCapability, OutputMode
from .subprocess_bridge import SubprocessEngine


class VibeVoiceEngine(SubprocessEngine):
    WSL_DISTRO = "Ubuntu"
    PYTHON = "/home/joneshong/.venvs/cosyvoice_vllm/bin/python3"
    RUNNER = "run_vibevoice.py"
    CWD = "/home/joneshong/VibeVoice"
    TIMEOUT_SEC = 600  # podcast 場景單次合成較長

    def _build_input(self, req, npy_out):
        if req.lang == "ja":
            raise ValueError("vibevoice 不支援日語，請走 indextts2_jmica 或 qwen3tts_gpu")
        d = super()._build_input(req, npy_out)
        d.update({
            "model_path": "/home/joneshong/vibevoice_models/VibeVoice-1.5B",
            # speakers: 多 speaker 場景透過 engine_specific["speakers"] 傳遞
            # [{"speaker_id": "master", "ref_wav": "...", "ref_text": "..."}, ...]
            "speakers": req.engine_specific.get("speakers", []),
        })
        return d

    def capability(self) -> EngineCapability:
        return EngineCapability(
            name="vibevoice",
            languages=["zh", "en"],
            multi_speaker=True,
            rtf_typical=1.2,
            vram_mb=8000,
            needs_wsl=True,
            needs_gpu=True,
            ref_duration_range=(3, 30),
            needs_ref_text=True,
            supported_outputs=[
                OutputMode.FILE, OutputMode.BUFFER, OutputMode.NUMPY,
                OutputMode.TENSOR, OutputMode.BASE64, OutputMode.STREAM,
            ],
            sample_rate=24000,
            notes="WSL2 community fork. 多 speaker / podcast，賣點 streaming。",
        )

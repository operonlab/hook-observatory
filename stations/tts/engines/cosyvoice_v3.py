"""CosyVoice v3 engine adapters — native (Windows) + vllm (WSL2) 兩 variants.

Reference inference: outputs/tts-finetune-test/v3/cosyvoice3_demo/run_v3_master_clone.py
Real API used:
    CosyVoice3(MODEL_DIR, load_trt=False, load_vllm=<flag>, fp16=False)
    .inference_zero_shot(text, prompt_text_with_sys, ref_wav, stream=False)
    .inference_cross_lingual(SYS_PROMPT + text, ref_wav, stream=False)
"""

from __future__ import annotations

from .base_v2 import EngineCapability, OutputMode
from .subprocess_bridge import SubprocessEngine

SYS_PROMPT = "You are a helpful assistant.<|endofprompt|>"


class CosyVoiceV3NativeEngine(SubprocessEngine):
    """Windows native CUDA inference (anaconda env=cosyvoice).

    Path 假設 win-gpu 端：
      Python:  C:/Users/User/anaconda3/envs/cosyvoice/python.exe
      Repo:    C:/Users/User/workshop/lab/cosyvoice
      Model:   pretrained_models/Fun-CosyVoice3-0.5B (relative to repo)
    Mac 端走 Fleet dispatch，這個檔案 import OK 但 healthcheck() 會 false。
    """

    PYTHON = "C:/Users/User/anaconda3/envs/cosyvoice/python.exe"
    RUNNER = "run_cosyvoice_v3.py"
    CWD = "C:/Users/User/workshop/lab/cosyvoice"
    EXTRA_ENV = {"PYTHONPATH": "C:/Users/User/workshop/lab/cosyvoice/third_party/Matcha-TTS"}
    TIMEOUT_SEC = 300

    def _build_input(self, req):
        d = super()._build_input(req)
        d.update(
            {
                "model_dir": "pretrained_models/Fun-CosyVoice3-0.5B",
                "use_vllm": False,
                "fp16": False,
                "sys_prompt": SYS_PROMPT,
            }
        )
        return d

    def capability(self) -> EngineCapability:
        return EngineCapability(
            name="cosyvoice_v3_native",
            languages=["zh", "en", "ja"],
            multi_speaker=False,
            rtf_typical=1.76,
            vram_mb=5000,
            needs_wsl=False,
            needs_gpu=True,
            ref_duration_range=(3, 30),
            needs_ref_text=False,
            supported_outputs=[
                OutputMode.FILE,
                OutputMode.BUFFER,
                OutputMode.NUMPY,
                OutputMode.TENSOR,
                OutputMode.BASE64,
            ],
            sample_rate=24000,
            notes="Windows native CUDA. Baseline RTF 1.76, 中文需 OpenCC t2s + 日文 pykakasi",
        )


class CosyVoiceV3VllmEngine(SubprocessEngine):
    """WSL2 vllm inference (uv venv ~/.venvs/cosyvoice_vllm).

    RTF 0.43，比 native 快 4.1×（少爺 2026-05-18 wedge 修復後實測）。
    預設 en 引擎。GPU wedge 風險已透過 TDR Registry 設防。
    """

    WSL_DISTRO = "Ubuntu"
    PYTHON = "/home/joneshong/.venvs/cosyvoice_vllm/bin/python3"
    RUNNER = "run_cosyvoice_v3.py"  # 共用同 runner，differ in_use_vllm
    # WSL home 內沒獨立 cosyvoice repo；走 9P /mnt/c 共享 Windows 端那份
    CWD = "/mnt/c/Users/User/workshop/lab/cosyvoice"
    TIMEOUT_SEC = 300

    def _build_input(self, req):
        d = super()._build_input(req)
        d.update(
            {
                "model_dir": "pretrained_models/Fun-CosyVoice3-0.5B",
                # 2026-05-19：vllm 0.x 與 transformers 4.57.3 衝突 (aimv2 重複 register)
                # 暫時降級 native PyTorch 推理路徑；待 vllm 升版（或 transformers 降版）再開
                "use_vllm": False,
                "fp16": False,
                "sys_prompt": SYS_PROMPT,
            }
        )
        return d

    def capability(self) -> EngineCapability:
        return EngineCapability(
            name="cosyvoice_v3_vllm",
            languages=["zh", "en", "ja"],
            multi_speaker=False,
            rtf_typical=0.43,
            vram_mb=7500,
            needs_wsl=True,
            needs_gpu=True,
            ref_duration_range=(3, 30),
            needs_ref_text=False,
            supported_outputs=[
                OutputMode.FILE,
                OutputMode.BUFFER,
                OutputMode.NUMPY,
                OutputMode.TENSOR,
                OutputMode.BASE64,
                OutputMode.STREAM,
            ],
            sample_rate=24000,
            notes="WSL2 + vllm. RTF 0.43，預設 en 首選。GPU wedge 已設 TDR.",
        )

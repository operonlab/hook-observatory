"""IndexTTS-2 engine — base (中英) + jmica (日語 fine-tune) 雙 variant.

Reference: stations/tts/engines/index_tts.py (Mac subprocess pattern, v0.2.0)
Real binary: lab/indextts/.venv/bin/indextts CLI（uv venv 已存在）。

雙 variant 差異：
- base:   checkpoints/      （原版，中英強）
- jmica:  checkpoints_ja/   （fine-tune，**只接 ja**；中英已 catastrophic forgetting）

VRAM 各 ~7GB，不能同時 keep alive → lifecycle.py 管 idle unload。
"""

from __future__ import annotations

from .base_v2 import EngineCapability, OutputMode
from .subprocess_bridge import SubprocessEngine


class IndexTTS2BaseEngine(SubprocessEngine):
    """IndexTTS-2 原版 ckpt — 中英。"""

    PYTHON = "C:/Users/User/workshop/lab/indextts/.venv/Scripts/python.exe"
    RUNNER = "run_indextts2.py"
    CWD = "C:/Users/User/workshop/lab/indextts"
    TIMEOUT_SEC = 300

    def _build_input(self, req, npy_out):
        d = super()._build_input(req, npy_out)
        d.update({
            "checkpoint_dir": "checkpoints",
            "config_yaml": "checkpoints/config_abs.yaml",
            "device": "cuda",
        })
        return d

    def capability(self) -> EngineCapability:
        return EngineCapability(
            name="indextts2_base",
            languages=["zh", "en"],
            multi_speaker=False,
            rtf_typical=0.7,
            vram_mb=7000,
            needs_wsl=False,
            needs_gpu=True,
            ref_duration_range=(5, 15),
            needs_ref_text=False,
            supported_outputs=[
                OutputMode.FILE, OutputMode.BUFFER, OutputMode.NUMPY,
                OutputMode.TENSOR, OutputMode.BASE64,
            ],
            sample_rate=22050,
            notes="Windows native uv venv. 少爺偏好中英音色。繁體需 OpenCC t2s.",
        )


class IndexTTS2JmicaEngine(SubprocessEngine):
    """IndexTTS-2 jmica fine-tune — 只接 ja。"""

    PYTHON = "C:/Users/User/workshop/lab/indextts/.venv/Scripts/python.exe"
    RUNNER = "run_indextts2.py"
    CWD = "C:/Users/User/workshop/lab/indextts"
    TIMEOUT_SEC = 300

    def _build_input(self, req, npy_out):
        # 守門：jmica 只接 ja，其他語言應由 routing 攔下（fail-loud）
        if req.lang not in ("ja", "auto"):
            raise ValueError(
                f"indextts2_jmica 只接 ja，收到 lang={req.lang}；"
                "中英請走 indextts2_base（routing.py 已預設）"
            )
        d = super()._build_input(req, npy_out)
        d.update({
            "checkpoint_dir": "checkpoints_ja",
            "config_yaml": "checkpoints_ja/config_abs.yaml",
            "device": "cuda",
        })
        return d

    def capability(self) -> EngineCapability:
        return EngineCapability(
            name="indextts2_jmica",
            languages=["ja"],
            multi_speaker=False,
            rtf_typical=0.7,
            vram_mb=7000,
            needs_wsl=False,
            needs_gpu=True,
            ref_duration_range=(5, 15),
            needs_ref_text=False,
            supported_outputs=[
                OutputMode.FILE, OutputMode.BUFFER, OutputMode.NUMPY,
                OutputMode.TENSOR, OutputMode.BASE64,
            ],
            sample_rate=22050,
            notes="Fine-tune jmica，中英 catastrophic forgetting，只接 ja",
        )

#!/usr/bin/env python3
"""worker_indextts_daemon — Windows native lab/indextts/.venv, hosts IndexTTS-2.

啟動：win-gpu native PowerShell spawn:
    C:/Users/User/workshop/lab/indextts/.venv/Scripts/python.exe \
        C:/Users/User/workshop-station/stations/tts/workers/worker_indextts_daemon.py

CWD: C:/Users/User/workshop/lab/indextts (供 import indextts module)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from base_daemon import WorkerDaemon


class WorkerIndexTTSDaemon(WorkerDaemon):
    LAB_INDEXTTS = "C:/Users/User/workshop/lab/indextts"
    # Windows path for voices/ — different mount than WSL workers
    VOICES_DIR_DEFAULT = "C:/Users/User/workshop-station/stations/tts/voices"

    def __init__(self):
        super().__init__()
        self.engine_obj = None

    def supported_engines(self) -> list[str]:
        return ["indextts2_base", "indextts2_jmica"]

    def _do_load(self, engine_name: str, **kwargs) -> None:
        # CWD 要對才能 import indextts package
        os.chdir(self.LAB_INDEXTTS)
        ckpt_dir = "checkpoints" if engine_name == "indextts2_base" else "checkpoints_ja"

        # Mandatory BEFORE importing indextts → deepspeed → C++ JIT toolchain:
        # native fd 1 must point to stderr so LINK errors / nvcc test output
        # don't bleed into our JSONL protocol. main_loop already backed up the
        # protocol fd.
        self.redirect_native_stdout_to_stderr()

        from indextts.infer_v2 import IndexTTS2

        # Performance flags (2026-05-20 RTF 2.5 → 1.0-1.5 expected on RTX 3090):
        #   use_fp16=True            — GPT autoregressive ~1.5-2× faster
        #   use_cuda_kernel=True     — BigVGan vocoder fused activation ~1.2-1.5×
        #   use_deepspeed=True       — transformer inference optimizer
        #     (DeepSpeed Windows wheel 0.17.5+e1560d84 from 6Morpheus6/deepspeed-windows-wheels;
        #     IndexTTS2 ctor has graceful try/except fallback if import fails — see
        #     infer_v2.py:92-95)
        self.engine_obj = IndexTTS2(
            model_dir=ckpt_dir,
            cfg_path=f"{ckpt_dir}/config.yaml",
            device="cuda:0",
            use_fp16=True,
            use_cuda_kernel=True,
            use_deepspeed=True,
        )

    def _do_unload(self) -> None:
        if self.engine_obj is not None:
            del self.engine_obj
            self.engine_obj = None
        import gc

        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _do_synth(
        self,
        text: str,
        lang: str,
        voice_id: str,
        ref_wav: str,
        ref_text: str,
        **kwargs,
    ):
        if lang == "zh":
            text = self.to_simplified(text)
        # IndexTTS-2 內部用 flow matching vocoder（diffusion 家族），同樣需要
        # explicit seed 才能跨段 / 重跑 deterministic。
        self.seed_rngs()
        # indextts2_jmica 只接 ja，base 接 zh/en — engine gate at load time
        import tempfile

        import soundfile as sf

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tmp_wav = tf.name
        try:
            self.engine_obj.infer(spk_audio_prompt=ref_wav, text=text, output_path=tmp_wav)
            audio, sr = sf.read(tmp_wav, dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            return audio, int(sr)
        finally:
            try:
                os.unlink(tmp_wav)
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(WorkerIndexTTSDaemon().main_loop())

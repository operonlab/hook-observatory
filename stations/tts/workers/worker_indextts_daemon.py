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

# 8-dim emotion vector order matches IndexTTS-2's emo_bias in
# lab/indextts/indextts/infer_v2.py (line 344):
#   [happy, angry, sad, afraid, disgusted, melancholic, surprised, calm]
EMOTION_PRESETS: dict[str, list[float]] = {
    "happy":       [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "angry":       [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "sad":         [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "afraid":      [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
    "disgusted":   [0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
    "melancholic": [0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
    "surprised":   [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
    "calm":        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
    "neutral":     [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
}


def _resolve_emotion(emotion: dict | None) -> dict:
    """Translate engine_specific.emotion → IndexTTS-2 infer() kwargs.

    Priority (matches infer_v2.py L396-410): emo_audio > emo_text > vector/preset.
    Returns a dict ready to splat into infer(); empty dict when no emotion given.
    """
    if not emotion or not isinstance(emotion, dict):
        return {}
    alpha = float(emotion.get("alpha", 1.0))
    alpha = max(0.0, min(1.0, alpha))
    out: dict = {"emo_alpha": alpha}

    if emotion.get("audio"):
        out["emo_audio_prompt"] = emotion["audio"]
        return out

    if emotion.get("text"):
        out["use_emo_text"] = True
        out["emo_text"] = emotion["text"]
        return out

    vec = emotion.get("vector")
    if vec is None and emotion.get("preset"):
        preset = str(emotion["preset"]).lower()
        if preset not in EMOTION_PRESETS:
            raise ValueError(
                f"unknown emotion preset '{preset}'; "
                f"choose from {sorted(EMOTION_PRESETS)}"
            )
        vec = EMOTION_PRESETS[preset]
    if vec is not None:
        if len(vec) != 8:
            raise ValueError(f"emotion vector must be 8-dim, got {len(vec)}")
        out["emo_vector"] = [float(v) for v in vec]
    return out


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

        # Performance flags (2026-05-20 RFC outputs/indextts-perf-rfc/RFC.md):
        #   use_fp16=True            — GPT autoregressive ~1.5-2×
        #   use_cuda_kernel=True     — BigVGan vocoder fused activation ~1.2-1.5×
        #   use_accel=True           — AccelInferenceEngine (paged KV + CUDA Graph +
        #                              FlashAttention + @torch.compile sampler).
        #                              Routes GPT generate to indextts/accel/ path
        #                              (gpt/model_v2.py:761), 1.5-2.5× hot-path speedup.
        #   use_torch_compile=True   — s2mel CFM vocoder torch.compile (~1.2-1.4×)
        #   use_deepspeed=False      — accel supersedes deepspeed wrapping; keeping
        #                              deepspeed True pays ~70s cold-load with no
        #                              hot-path benefit (line 761 if/else gate).
        self.engine_obj = IndexTTS2(
            model_dir=ckpt_dir,
            cfg_path=f"{ckpt_dir}/config.yaml",
            device="cuda:0",
            use_fp16=True,
            use_cuda_kernel=True,
            # use_accel=True 需 flash_attn；Windows native build hdim128+bf16+sm80
            # 在 nvcc 12.8 + MSVC 14.44 編不過（cutlass template 不相容，業界共識）。
            # 候選解：搬 indextts 到 WSL2 venv (cosyvoice/qwen3 同路線) 才能跑 Linux 路徑
            # flash_attn install。暫關。
            use_accel=False,
            use_torch_compile=False,  # 2026-05-20 ablation: torch_compile s2mel 對 RTF 影響微 (+0.1)
            # 2026-05-20 ablation: use_deepspeed=False 反而 RTF 從 1.21→1.89 慢 56%。
            # RFC 假設「accel 開了 ds 用不到」錯 — accel 沒開時 ds 仍是必要 GPT wrapper。
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

        emo_kwargs = _resolve_emotion(kwargs.get("emotion"))

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tmp_wav = tf.name
        try:
            self.engine_obj.infer(
                spk_audio_prompt=ref_wav,
                text=text,
                output_path=tmp_wav,
                **emo_kwargs,
            )
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

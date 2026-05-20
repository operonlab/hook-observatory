#!/usr/bin/env python3
"""worker_qwen3_daemon — tts-qwen3 venv 內常駐，hosts qwen3tts_gpu.

啟動：win-gpu WSL2 端 station main.py spawn:
    /home/joneshong/.venvs/tts-qwen3/bin/python3 \
        /mnt/c/Users/User/workshop-station/stations/tts/workers/worker_qwen3_daemon.py

獨立 venv 避免 cosyvoice_vllm 的 transformers 4.51.3 vs qwen-tts 套件衝突.

少爺指出「qwen3tts 聽不懂內容」— 試多種 language 編碼形式（lang code vs full name）.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from base_daemon import WorkerDaemon

# Qwen3-TTS official API (qwen-tts PyPI, get_supported_languages() 實測 2026-05-20):
# Supported: ['auto', 'chinese', 'english', 'french', 'german', 'italian',
#             'japanese', 'korean', 'portuguese', 'russian', 'spanish']
# 一律小寫 full name；非此清單會 ValueError("Unsupported languages: [...]").
_LANG_FALLBACK = {
    "zh": ["chinese"],
    "en": ["english"],
    "ja": ["japanese"],
    "ko": ["korean"],
}


class WorkerQwen3Daemon(WorkerDaemon):
    MODEL_PATH = "/home/joneshong/qwen3tts_models/Qwen3-TTS-12Hz-0.6B-Base"

    def __init__(self):
        super().__init__()
        self.model = None
        self._supported_languages: list[str] | None = None

    def supported_engines(self) -> list[str]:
        return ["qwen3tts_gpu"]

    def _do_load(self, engine_name: str, **kwargs) -> None:
        model_path = kwargs.get("model_path", self.MODEL_PATH)
        import torch
        from qwen_tts import Qwen3TTSModel

        # 對齊官方 HF model card 範例 — 不傳 device_map+dtype 會走 CPU/float32
        # 預設造成「daemon timeout 300s + 0.16s 短輸出」(round 9 真因).
        self.model = Qwen3TTSModel.from_pretrained(
            model_path,
            device_map="cuda:0",
            dtype=torch.bfloat16,
            # flash_attention_2 需 pip install flash-attn — 略過，model card 標明可選
        )
        # 探查 supported languages 以便後續挑對的格式
        try:
            self._supported_languages = list(self.model.get_supported_languages())
        except Exception:
            self._supported_languages = None

    def _do_unload(self) -> None:
        if self.model is not None:
            del self.model
            self.model = None
        import gc

        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _resolve_language(self, lang: str) -> str:
        """Pick the right language string by intersecting model's supported list."""
        candidates = _LANG_FALLBACK.get(lang, [lang])
        if self._supported_languages:
            supported = set(self._supported_languages)
            for c in candidates:
                if c in supported:
                    return c
        # Fallback: first candidate
        return candidates[0]

    def _do_synth(
        self,
        text: str,
        lang: str,
        voice_id: str,
        ref_wav: str,
        ref_text: str,
        **kwargs,
    ):
        if not ref_text:
            raise RuntimeError(
                f"qwen3tts zero-shot 需要 ref_text，但 voice_id={voice_id} 的 .transcript 為空"
            )
        if lang == "zh":
            text = self.to_simplified(text)
            if ref_text:
                ref_text = self.to_simplified(ref_text)

        import numpy as np

        # Qwen3-TTS 內部 token sampler (do_sample=True, temp=0.9) — 即使
        # repetition_penalty 已壓住明顯 collapse，輸出仍非 deterministic。
        # 跟 cosyvoice / vibevoice 一致 seed，讓 SSE 跨段穩。
        self.seed_rngs()

        language = self._resolve_language(lang)
        # 官方 hard_defaults: repetition_penalty=1.05, max_new_tokens=2048, do_sample=True.
        # 偶發 repetition collapse（觀察到日文長句 + 連續 -masu 結尾 → "歩歩歩歩" hallucination,
        # 同 input 重跑時好時壞）。raise repetition_penalty 至 1.2 抑制 token 重複；
        # max_new_tokens=1024（仍可容納 ~85s 音檔）擋 over-generation。
        audios, sr = self.model.generate_voice_clone(
            text=text,
            language=language,
            ref_audio=ref_wav,
            ref_text=ref_text,
            repetition_penalty=1.2,
            max_new_tokens=1024,
        )
        if isinstance(audios, list):
            audio = np.concatenate([np.asarray(a, dtype=np.float32).squeeze() for a in audios])
        else:
            audio = np.asarray(audios, dtype=np.float32).squeeze()
        return audio, int(sr)


if __name__ == "__main__":
    sys.exit(WorkerQwen3Daemon().main_loop())

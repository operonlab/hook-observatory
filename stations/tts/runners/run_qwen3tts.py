#!/usr/bin/env python3
"""Qwen3-TTS GPU runner — qwen_tts package + voice clone (WSL2).

執行環境（win-gpu WSL2）：
  Venv:    ~/.venvs/tts-qwen3  (transformers main + torch cu121 + qwen-tts package)
  Model:   ~/qwen3tts_models/Qwen3-TTS-12Hz-0.6B-Base

API 路徑（2026-05-19 round 5 對齊）：
  transformers main 仍未 ship qwen3_tts model_type，但官方 `qwen-tts` PyPI 套件
  自帶 Qwen3TTSModel + generate_voice_clone()，繞過 AutoModelForCausalLM.

  from qwen_tts import Qwen3TTSModel
  model = Qwen3TTSModel.from_pretrained(path)
  audios, sr = model.generate_voice_clone(text, language, ref_audio, ref_text)

Input JSON (stdin):
  text, lang, voice_id, speed, model_path
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import read_input, resolve_voice_ref, to_simplified, write_err, write_ok

# Qwen3-TTS language code 對應（HF model card 規約）
_LANG_MAP = {"zh": "Chinese", "en": "English", "ja": "Japanese", "ko": "Korean"}


def main():
    try:
        inp = read_input()
        text = inp["text"]
        lang = inp["lang"]
        voice_id = inp.get("voice_id", "master")
        model_path = inp.get(
            "model_path", "/home/joneshong/qwen3tts_models/Qwen3-TTS-12Hz-0.6B-Base"
        )

        if lang == "zh":
            text = to_simplified(text)

        ref_wav, ref_text = resolve_voice_ref(voice_id)
        if not ref_wav:
            write_err(f"voice_id={voice_id} 找不到 ref wav")
            sys.exit(1)
        if not ref_text:
            write_err(f"qwen3tts zero-shot 需 ref_text，但 {voice_id}.transcript 為空")
            sys.exit(1)

        import numpy as np

        # 用官方 qwen-tts PyPI 套件 — 自帶 Qwen3TTSModel class，不走 transformers AutoConfig
        from qwen_tts import Qwen3TTSModel

        model = Qwen3TTSModel.from_pretrained(model_path)

        language = _LANG_MAP.get(lang, lang)
        audios, sr = model.generate_voice_clone(
            text=text,
            language=language,
            ref_audio=ref_wav,
            ref_text=ref_text,
        )

        # audios is List[np.ndarray]; mono concat
        audio = (
            np.concatenate([a.astype(np.float32).squeeze() for a in audios])
            if isinstance(audios, list)
            else np.asarray(audios, dtype=np.float32).squeeze()
        )
        write_ok(audio, int(sr))
    except Exception as e:
        write_err(str(e))
        sys.exit(2)


if __name__ == "__main__":
    main()

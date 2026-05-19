#!/usr/bin/env python3
"""Qwen3-TTS GPU runner — HuggingFace 0.6B-Base zero-shot (WSL2).

執行環境（win-gpu WSL2）：
  Venv:    ~/.venvs/cosyvoice_vllm
  Model:   ~/qwen3tts_models/Qwen3-TTS-12Hz-0.6B-Base

Input JSON (stdin):
  text, lang, voice_id, speed, npy_out, model_path
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import read_input, resolve_voice_ref, to_simplified, write_err, write_ok


def main():
    try:
        inp = read_input()
        text = inp["text"]
        lang = inp["lang"]
        voice_id = inp.get("voice_id", "master")
        model_path = inp.get("model_path", "/home/joneshong/qwen3tts_models/Qwen3-TTS-12Hz-0.6B-Base")
        npy_out = inp["npy_out"]

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
        import soundfile as sf
        import torch  # noqa: F401
        from transformers import AutoModelForCausalLM, AutoTokenizer

        # Qwen3-TTS-0.6B-Base 的 generate_voice_clone API
        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            model_path, trust_remote_code=True, torch_dtype="bfloat16", device_map="cuda"
        )

        # 視 model 內部實作而定；以下對應 Qwen3-TTS-0.6B-Base 公開的 API：
        audio_out_path = npy_out + ".tmp.wav"
        model.generate_voice_clone(
            text=text,
            ref_wav=ref_wav,
            ref_text=ref_text,
            output_path=audio_out_path,
            tokenizer=tokenizer,
        )

        audio, sr = sf.read(audio_out_path, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        np.save(npy_out, audio.astype(np.float32))
        try:
            os.unlink(audio_out_path)
        except Exception:
            pass

        write_ok(npy_out, int(sr))
    except Exception as e:
        write_err(str(e))
        sys.exit(2)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""CosyVoice v3 runner — native + vllm 共用（差別只在 load_vllm flag）.

執行環境（win-gpu）：
  Native: anaconda env=cosyvoice    /  CWD=lab/cosyvoice
  Vllm:   ~/.venvs/cosyvoice_vllm   /  CWD=~/workshop/lab/cosyvoice

Input JSON (stdin):
  text, lang, voice_id, speed, npy_out, model_dir, use_vllm, fp16, sys_prompt
Output JSON (stdout last line):
  {"ok": true, "npy_path": ..., "sample_rate": ...}
"""

from __future__ import annotations

import os
import sys

# 必須在 import cosyvoice 前加 sys.path（讓 third_party/Matcha-TTS 可被找到）
sys.path.insert(0, "third_party/Matcha-TTS")

# Runner 自己住在 stations/tts/runners/，加 parent 進 path 取 _common
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import read_input, resolve_voice_ref, to_katakana_spaced, to_simplified, write_err, write_ok


def main():
    try:
        inp = read_input()
        text = inp["text"]
        lang = inp["lang"]
        speed = float(inp.get("speed", 1.0))
        voice_id = inp.get("voice_id", "master")
        sys_prompt = inp.get("sys_prompt", "You are a helpful assistant.<|endofprompt|>")
        model_dir = inp.get("model_dir", "pretrained_models/Fun-CosyVoice3-0.5B")
        use_vllm = bool(inp.get("use_vllm", False))
        fp16 = bool(inp.get("fp16", False))
        npy_out = inp["npy_out"]

        # 語言預處理
        if lang == "zh":
            text = to_simplified(text)
        elif lang == "ja":
            text = to_katakana_spaced(text)

        ref_wav, ref_transcript = resolve_voice_ref(voice_id)
        if not ref_wav:
            write_err(f"voice_id={voice_id} 找不到 ref wav (voices_dir 沒對應檔案)")
            sys.exit(1)

        # 防呆：繁→簡 也對 ref_transcript 套用（避免 ref text 是繁體）
        if ref_transcript:
            ref_transcript = to_simplified(ref_transcript)

        import numpy as np
        import torch  # noqa: F401
        from cosyvoice.cli.cosyvoice import CosyVoice3

        cosy = CosyVoice3(model_dir, load_trt=False, load_vllm=use_vllm, fp16=fp16)

        # 中文同語走 zero_shot（音色最穩）；英日走 cross_lingual
        if lang == "zh" and ref_transcript:
            prompt_text_with_sys = sys_prompt + ref_transcript
            gen = cosy.inference_zero_shot(text, prompt_text_with_sys, ref_wav, stream=False, speed=speed)
        else:
            gen = cosy.inference_cross_lingual(sys_prompt + text, ref_wav, stream=False, speed=speed)

        chunks = []
        for j in gen:
            chunks.append(j["tts_speech"])
        if not chunks:
            write_err("CosyVoice produced no output")
            sys.exit(1)

        wav_tensor = torch.cat(chunks, dim=-1)
        audio = wav_tensor.squeeze().cpu().numpy().astype("float32")
        np.save(npy_out, audio)
        write_ok(npy_out, int(cosy.sample_rate))
    except Exception as e:
        write_err(str(e))
        sys.exit(2)


if __name__ == "__main__":
    main()

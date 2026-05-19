#!/usr/bin/env python3
"""VibeVoice runner — multi-speaker / podcast (WSL2).

執行環境（win-gpu WSL2）：
  Venv: ~/.venvs/cosyvoice_vllm
  CWD:  ~/VibeVoice (community fork)

Input JSON (stdin):
  text, lang, voice_id, speed, npy_out, model_path, speakers
  speakers: [{"speaker_id": "master", "ref_wav": "...", "ref_text": "..."}, ...]
            空陣列 → 單 speaker 模式，用 voice_id 查 ref
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# VibeVoice community fork 的 inference module
sys.path.insert(0, os.path.expanduser("~/VibeVoice"))

from _common import read_input, resolve_voice_ref, to_simplified, write_err, write_ok


def main():
    try:
        inp = read_input()
        text = inp["text"]
        lang = inp["lang"]
        voice_id = inp.get("voice_id", "master")
        model_path = inp.get("model_path", "/home/joneshong/vibevoice_models/VibeVoice-1.5B")
        speakers = inp.get("speakers", [])
        npy_out = inp["npy_out"]

        if lang == "ja":
            write_err("vibevoice 不支援日語")
            sys.exit(1)
        if lang == "zh":
            text = to_simplified(text)

        # 單 speaker fallback
        if not speakers:
            ref_wav, ref_text = resolve_voice_ref(voice_id)
            if not ref_wav:
                write_err(f"voice_id={voice_id} 找不到 ref wav")
                sys.exit(1)
            speakers = [{"speaker_id": voice_id, "ref_wav": ref_wav, "ref_text": ref_text}]

        import numpy as np
        from vibevoice.modular.modeling_vibevoice_inference import (
            VibeVoiceForConditionalGenerationInference,
        )
        from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor

        proc = VibeVoiceProcessor.from_pretrained(model_path)
        model = VibeVoiceForConditionalGenerationInference.from_pretrained(
            model_path, torch_dtype="bfloat16", device_map="cuda"
        )

        # 多 speaker 場景：text 內含 "[Speaker X]" 標籤，VibeVoice 自己 parse
        voice_samples = [s["ref_wav"] for s in speakers]
        inputs = proc(
            text=[text],
            voice_samples=[voice_samples],
            padding=True,
            return_tensors="pt",
            return_attention_mask=True,
        ).to("cuda")

        out = model.generate(**inputs, max_new_tokens=None)
        # VibeVoice 輸出 raw audio tensor on .speech_outputs
        audio = out.speech_outputs[0].cpu().numpy().astype(np.float32).squeeze()
        sr = 24000  # VibeVoice 1.5B 預設

        np.save(npy_out, audio)
        write_ok(npy_out, sr)
    except Exception as e:
        write_err(str(e))
        sys.exit(2)


if __name__ == "__main__":
    main()

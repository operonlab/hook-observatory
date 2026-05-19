#!/usr/bin/env python3
"""IndexTTS-2 runner — base + jmica 共用（差別只在 checkpoint_dir）.

執行環境（win-gpu）：
  Venv: lab/indextts/.venv (uv)
  CWD:  lab/indextts

Input JSON (stdin):
  text, lang, voice_id, speed, npy_out, checkpoint_dir, config_yaml, device
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
        ckpt_dir = inp.get("checkpoint_dir", "checkpoints")
        config_yaml = inp.get("config_yaml", "checkpoints/config_abs.yaml")
        device = inp.get("device", "cuda")
        npy_out = inp["npy_out"]

        if lang == "zh":
            text = to_simplified(text)

        ref_wav, _ = resolve_voice_ref(voice_id)
        if not ref_wav:
            write_err(f"voice_id={voice_id} 找不到 ref wav")
            sys.exit(1)

        # IndexTTS2 Python API（避免 CLI subprocess 多一層 overhead）
        # 對應 lab/indextts repo 的 IndexTTS2 類別
        import numpy as np
        import soundfile as sf

        from indextts.infer_v2 import IndexTTS2  # 對應 IndexTTS-2 repo 結構

        tts = IndexTTS2(model_dir=ckpt_dir, cfg_path=config_yaml, device=device)

        # output 走 tmp wav 再 load 成 numpy
        tmp_wav = npy_out + ".tmp.wav"
        tts.infer(
            spk_audio_prompt=ref_wav,
            text=text,
            output_path=tmp_wav,
        )

        audio, sr = sf.read(tmp_wav, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)  # to mono
        np.save(npy_out, audio.astype(np.float32))
        try:
            os.unlink(tmp_wav)
        except Exception:
            pass

        write_ok(npy_out, int(sr))
    except Exception as e:
        write_err(str(e))
        sys.exit(2)


if __name__ == "__main__":
    main()

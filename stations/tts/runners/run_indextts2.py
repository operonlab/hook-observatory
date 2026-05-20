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

# 8-dim emotion preset order matches IndexTTS-2's emo_bias in
# lab/indextts/indextts/infer_v2.py (line 344):
#   [happy, angry, sad, afraid, disgusted, melancholic, surprised, calm]
EMOTION_PRESETS = {
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


def _resolve_emotion(emotion):
    """Translate engine_specific.emotion → IndexTTS-2 infer() kwargs."""
    if not emotion or not isinstance(emotion, dict):
        return {}
    alpha = float(emotion.get("alpha", 1.0))
    alpha = max(0.0, min(1.0, alpha))
    out = {"emo_alpha": alpha}
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


def main():
    try:
        inp = read_input()
        text = inp["text"]
        lang = inp["lang"]
        voice_id = inp.get("voice_id", "master")
        ckpt_dir = inp.get("checkpoint_dir", "checkpoints")
        config_yaml = inp.get("config_yaml", "checkpoints/config_abs.yaml")
        device = inp.get("device", "cuda")
        # engine_specific arrives either flattened (subprocess_bridge attaches
        # the whole dict to inp) or nested under "engine_specific"; accept both.
        emotion = inp.get("emotion")
        if emotion is None and isinstance(inp.get("engine_specific"), dict):
            emotion = inp["engine_specific"].get("emotion")
        emo_kwargs = _resolve_emotion(emotion)

        if lang == "zh":
            text = to_simplified(text)

        ref_wav, _ = resolve_voice_ref(voice_id)
        if not ref_wav:
            write_err(f"voice_id={voice_id} 找不到 ref wav")
            sys.exit(1)

        # IndexTTS2 Python API（避免 CLI subprocess 多一層 overhead）
        # 對應 lab/indextts repo 的 IndexTTS2 類別
        import tempfile

        import soundfile as sf

        from indextts.infer_v2 import IndexTTS2  # 對應 IndexTTS-2 repo 結構

        tts = IndexTTS2(model_dir=ckpt_dir, cfg_path=config_yaml, device=device)

        # IndexTTS infer() 寫到 disk → 我們讀 numpy 後走 stdout base64 回 host
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tmp_wav = tf.name
        try:
            tts.infer(
                spk_audio_prompt=ref_wav,
                text=text,
                output_path=tmp_wav,
                **emo_kwargs,
            )
            audio, sr = sf.read(tmp_wav, dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            write_ok(audio, int(sr))
        finally:
            try:
                os.unlink(tmp_wav)
            except Exception:
                pass
    except Exception as e:
        write_err(str(e))
        sys.exit(2)


if __name__ == "__main__":
    main()

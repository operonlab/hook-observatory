"""Runner 共用工具 — read stdin JSON / write stdout JSON / OpenCC / pykakasi."""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any


def read_input() -> dict[str, Any]:
    raw = sys.stdin.read()
    return json.loads(raw)


def write_ok(npy_path: str, sample_rate: int) -> None:
    print(json.dumps({"ok": True, "npy_path": npy_path, "sample_rate": sample_rate}))


def write_err(msg: str) -> None:
    print(json.dumps({"ok": False, "error": msg, "trace": traceback.format_exc()}))


_t2s = None


def to_simplified(text: str) -> str:
    """繁→簡 (CosyVoice/IndexTTS/Qwen3 all trained on simplified)."""
    global _t2s
    if _t2s is None:
        try:
            from opencc import OpenCC
            _t2s = OpenCC("t2s")
        except ImportError:
            logging.warning("opencc not installed in this venv; skipping 繁→簡")
            return text
    return _t2s.convert(text)


_kakasi = None


def to_katakana_spaced(text: str) -> str:
    """日文 → 片假名 + 空格切詞 (CosyVoice 日語必處理)."""
    global _kakasi
    if _kakasi is None:
        try:
            import pykakasi
            _kakasi = pykakasi.kakasi()
        except ImportError:
            logging.warning("pykakasi not installed; falling back to raw text")
            return text
    parts = _kakasi.convert(text)
    return " ".join(p["kana"] for p in parts if p.get("kana"))


def resolve_voice_ref(voice_id: str, voices_dir: str | None = None) -> tuple[str | None, str]:
    """Look up voice ref + transcript by voice_id.

    Search order:
      1. voices_dir / {voice_id}.wav
      2. ${STATIONS_TTS_VOICES} / {voice_id}.wav
      3. Absolute path passthrough (voice_id starts with / or drive letter)
    """
    if voice_id.startswith("/") or (len(voice_id) > 2 and voice_id[1] == ":"):
        # Absolute path passthrough
        return (voice_id, "")

    candidates = []
    if voices_dir:
        candidates.append(Path(voices_dir))
    env_dir = os.environ.get("STATIONS_TTS_VOICES")
    if env_dir:
        candidates.append(Path(env_dir))
    # 預設：runner 在 stations/tts/runners/ 下，往上找 voices/
    candidates.append(Path(__file__).parent.parent / "voices")

    for base in candidates:
        wav = base / f"{voice_id}.wav"
        if wav.exists():
            transcript_file = base / f"{voice_id}.transcript"
            transcript = transcript_file.read_text().strip() if transcript_file.exists() else ""
            return (str(wav), transcript)
    return (None, "")

"""Worker daemon base — JSONL stdin/stdout protocol for persistent TTS engine workers.

少爺 2026-05-19 規格：
- 每個 worker 一個常駐 Python process，住在各自 venv (tts-trio / tts-qwen3)
- model_pool max=1 (跨 worker)，由 station 端 lock 控制
- 子類實作 _load(engine_name, **kw), _unload(), _synth(text, lang, voice_id, ref_wav, ref_text, **kw)
- 主迴圈讀 stdin JSONL，回 stdout JSONL

Protocol (one JSON per line):
  → {"op": "load", "engine": "<name>", "voice_dir": "/path", ...}
  ← {"ok": true, "loaded": "<name>"}
  → {"op": "synth", "text": "...", "lang": "zh", "voice_id": "master"}
  ← {"ok": true, "audio_b64": "...", "sample_rate": 24000, "duration_s": 3.5, "rtf": 0.42}
  → {"op": "unload"}
  ← {"ok": true, "loaded": null}
  → {"op": "ping"}
  ← {"ok": true, "loaded": "<name>"|null}

Error:
  ← {"ok": false, "error": "...", "trace": "..."}
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class WorkerDaemon(ABC):
    """Subclass per venv group; manages one engine in GPU at a time."""

    VOICES_DIR_DEFAULT = "/mnt/c/Users/User/workshop-station/stations/tts/voices"

    def __init__(self):
        self.current_engine_name: str | None = None
        self._opencc = None
        self._kakasi = None

    # ---- Required subclass overrides ----

    @abstractmethod
    def _do_load(self, engine_name: str, **kwargs) -> None:
        """Load `engine_name` into self.current_engine_obj. Raise on failure."""

    @abstractmethod
    def _do_unload(self) -> None:
        """Release current engine + free GPU memory."""

    @abstractmethod
    def _do_synth(
        self,
        text: str,
        lang: str,
        voice_id: str,
        ref_wav: str,
        ref_text: str,
        **kwargs,
    ) -> tuple[numpy.ndarray, int]:
        """Run inference. Return (float32 mono audio, sample_rate)."""

    @abstractmethod
    def supported_engines(self) -> list[str]:
        """List engine names this worker can load."""

    # ---- Voice resolution ----

    def resolve_voice_ref(
        self, voice_id: str, voices_dir: str | None = None
    ) -> tuple[str | None, str]:
        if voice_id.startswith("/") or (len(voice_id) > 2 and voice_id[1] == ":"):
            return (voice_id, "")
        candidates = []
        if voices_dir:
            candidates.append(Path(voices_dir))
        env_dir = os.environ.get("STATIONS_TTS_VOICES")
        if env_dir:
            candidates.append(Path(env_dir))
        candidates.append(Path(self.VOICES_DIR_DEFAULT))
        for base in candidates:
            wav = base / f"{voice_id}.wav"
            if wav.exists():
                transcript_file = base / f"{voice_id}.transcript"
                transcript = (
                    transcript_file.read_text(encoding="utf-8").strip()
                    if transcript_file.exists()
                    else ""
                )
                return (str(wav), transcript)
        return (None, "")

    # ---- Determinism + amplitude safety (shared across all engines) ----

    DEFAULT_SEED = 42
    PEAK_TARGET = 0.707  # -3 dBFS

    def seed_rngs(self, seed: int | None = None) -> None:
        """Seed torch / cuda RNG so diffusion / sampling models are deterministic.

        Subclass _do_synth() should call this before generate(). Centralized
        here so seed value is consistent across cosyvoice / vibevoice /
        indextts2 / qwen3 — and so stream endpoints get bit-identical output
        as the long endpoint.
        """
        seed = self.DEFAULT_SEED if seed is None else seed
        try:
            import torch

            torch.manual_seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)
        except ImportError:
            pass  # cosyvoice / qwen3 venvs always have torch; indextts also; safe-guard only

    # ---- Lang preprocessing ----

    def to_simplified(self, text: str) -> str:
        if self._opencc is None:
            try:
                from opencc import OpenCC

                self._opencc = OpenCC("t2s")
            except ImportError:
                return text
        return self._opencc.convert(text)

    def to_katakana_spaced(self, text: str) -> str:
        if self._kakasi is None:
            try:
                import pykakasi

                self._kakasi = pykakasi.kakasi()
            except ImportError:
                return text
        parts = self._kakasi.convert(text)
        return " ".join(p["kana"] for p in parts if p.get("kana"))

    # ---- Command dispatch ----

    def handle_cmd(self, cmd: dict[str, Any]) -> dict[str, Any]:
        op = cmd.pop("op", None)
        try:
            if op == "load":
                engine_name = cmd.pop("engine")
                if engine_name not in self.supported_engines():
                    return {
                        "ok": False,
                        "error": f"engine {engine_name} not supported by this worker",
                    }
                if self.current_engine_name == engine_name:
                    return {"ok": True, "loaded": engine_name, "msg": "already loaded"}
                if self.current_engine_name is not None:
                    self._do_unload()
                    self.current_engine_name = None
                self._do_load(engine_name, **cmd)
                self.current_engine_name = engine_name
                return {"ok": True, "loaded": engine_name}
            elif op == "synth":
                if self.current_engine_name is None:
                    return {"ok": False, "error": "no engine loaded; call load first"}
                t0 = time.time()
                ref_wav = cmd.get("ref_wav")
                ref_text = cmd.get("ref_text", "")
                if not ref_wav:
                    rw, rt = self.resolve_voice_ref(cmd.get("voice_id", "master"))
                    ref_wav = ref_wav or rw
                    ref_text = ref_text or rt
                if not ref_wav:
                    return {"ok": False, "error": f"voice_id={cmd.get('voice_id')} has no ref wav"}
                cmd["ref_wav"] = ref_wav
                cmd["ref_text"] = ref_text
                audio, sr = self._do_synth(**cmd)
                elapsed = time.time() - t0
                import numpy as np

                arr = np.asarray(audio, dtype=np.float32).squeeze()
                if arr.ndim > 1:
                    arr = arr.mean(axis=tuple(range(1, arr.ndim)))
                # Centralized peak normalize — prevents clipping when audio
                # is later concat'd across segments (stream / long endpoints)
                # or re-encoded. Threshold matches DDPM seed fix for
                # vibevoice but applies to all engines for consistency.
                peak = float(np.abs(arr).max())
                if peak > self.PEAK_TARGET:
                    arr = arr * (self.PEAK_TARGET / peak)
                duration = len(arr) / sr if sr else 0
                rtf = (elapsed / duration) if duration else float("inf")
                return {
                    "ok": True,
                    "audio_b64": base64.b64encode(arr.tobytes()).decode(),
                    "sample_rate": int(sr),
                    "duration_s": round(duration, 3),
                    "rtf": round(rtf, 4),
                    "shape": [int(arr.shape[0])],
                    "dtype": "float32",
                }
            elif op == "unload":
                if self.current_engine_name is not None:
                    self._do_unload()
                    self.current_engine_name = None
                return {"ok": True, "loaded": None}
            elif op == "ping":
                return {"ok": True, "loaded": self.current_engine_name}
            elif op == "shutdown":
                if self.current_engine_name is not None:
                    self._do_unload()
                return {"ok": True, "bye": True}
            else:
                return {"ok": False, "error": f"unknown op: {op}"}
        except Exception as e:
            return {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc()[-2000:],
            }

    def main_loop(self) -> int:
        # Critical: many ML libs print INFO/WARN to stdout at import time (vllm,
        # modelscope, qwen-tts, vibevoice). That pollutes our JSONL protocol.
        # Redirect stdout → stderr; keep a private fd for protocol responses.
        _real_stdout = sys.stdout
        sys.stdout = sys.stderr

        def _write(obj: dict[str, Any]) -> None:
            _real_stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            _real_stdout.flush()

        # Signal ready so station knows daemon is alive
        _write({"ready": True, "supported": self.supported_engines()})

        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                cmd = json.loads(raw)
            except json.JSONDecodeError as e:
                _write({"ok": False, "error": f"bad JSON: {e}"})
                continue
            result = self.handle_cmd(cmd)
            _write(result)
            if cmd.get("op") == "shutdown" or result.get("bye"):
                break
        return 0

"""Subprocess bridge base — engine adapter calls a runner script in its own venv.

對應 INTEGRATION-PLAN.md §6「transformers 版本衝突 → 不同 engine 走不同 venv」。
Station 主 venv 保持輕量（fastapi+httpx+pyyaml），每個 engine 的沉重依賴
（torch/cosyvoice/indextts/vllm/transformers/vibevoice）住在各自 venv，
透過 subprocess 呼叫對應的 runner script。

Runner I/O 規約（base64 走 stdout，跨 OS 安全）：
- stdin: JSON{text, lang, voice_id, ref_wav, ref_text, speed, engine_specific}
- stdout 最後一行: JSON{ok: bool, sample_rate: int, audio_b64: str (raw float32),
                       shape: [N], dtype: "float32", error: str?}
- 不使用檔案系統共享（解決 WSL/Windows path mismatch — reviewer Bug #1+#2 修補）
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from abc import abstractmethod
from pathlib import Path

import numpy as np

from .base_v2 import EngineCapability, SynthesizeRequest, TTSEngineV2

logger = logging.getLogger(__name__)


class SubprocessEngine(TTSEngineV2):
    """Each engine declares: python interpreter / runner script / cwd / env."""

    PYTHON: str = ""          # 例: "C:/Users/User/anaconda3/envs/cosyvoice/python.exe"
    WSL_DISTRO: str | None = None  # 設 "Ubuntu" 走 wsl.exe，否則 native
    RUNNER: str = ""          # 相對 stations/tts/runners/ 的 .py
    CWD: str = ""             # 執行目錄（cosyvoice 需 chdir 才能 import）
    EXTRA_ENV: dict[str, str] = {}
    TIMEOUT_SEC: int = 300

    def __init__(self):
        self._loaded = False  # subprocess 模式下 always False，保留欄位給 in-process 升級
        self._last_used = 0.0

    # ---- Subprocess command construction ----

    def _runner_abs_path(self) -> str:
        return str(Path(__file__).parent.parent / "runners" / self.RUNNER)

    def _build_cmd(self) -> list[str]:
        runner = self._runner_abs_path()
        if self.WSL_DISTRO:
            # Translate Windows paths to WSL paths if needed
            wsl_runner = self._to_wsl_path(runner)
            wsl_python = self.PYTHON  # already a WSL path expected
            shell_cmd = f"cd {self._to_wsl_path(self.CWD) if self.CWD else '~'} && {wsl_python} {wsl_runner}"
            return ["wsl.exe", "-d", self.WSL_DISTRO, "--", "bash", "-lc", shell_cmd]
        cmd = [self.PYTHON, runner]
        return cmd

    @staticmethod
    def _to_wsl_path(p: str) -> str:
        if not p:
            return p
        if p.startswith("/"):
            return p  # already POSIX
        # C:/foo → /mnt/c/foo
        if len(p) >= 3 and p[1] == ":":
            return "/mnt/" + p[0].lower() + p[2:].replace("\\", "/")
        return p

    # ---- I/O contract ----

    def _build_input(self, req: SynthesizeRequest) -> dict:
        return {
            "text": req.text,
            "lang": req.lang,
            "voice_id": req.voice_id,
            "speed": req.speed,
            "engine_specific": req.engine_specific,
        }

    def _synthesize_raw(self, req: SynthesizeRequest) -> tuple[np.ndarray, int]:
        import base64

        input_blob = self._build_input(req)
        cmd = self._build_cmd()

        env = os.environ.copy()
        env.update(self.EXTRA_ENV)
        logger.info(
            "Calling %s runner (lang=%s, len=%d)", self.capability().name, req.lang, len(req.text)
        )
        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd,
                input=json.dumps(input_blob).encode(),
                capture_output=True,
                cwd=self.CWD if not self.WSL_DISTRO else None,
                env=env,
                timeout=self.TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{self.capability().name} runner timeout > {self.TIMEOUT_SEC}s")
        elapsed = time.time() - t0

        stderr_tail = proc.stderr.decode(errors="replace")[-1000:] if proc.stderr else ""
        if proc.returncode != 0:
            raise RuntimeError(
                f"{self.capability().name} runner exit={proc.returncode}\n{stderr_tail}"
            )
        try:
            meta = json.loads(proc.stdout.decode(errors="replace").strip().splitlines()[-1])
        except Exception as e:
            raise RuntimeError(
                f"{self.capability().name} runner bad JSON output: {e}\nstderr={stderr_tail}"
            )
        if not meta.get("ok"):
            raise RuntimeError(f"{self.capability().name} failed: {meta.get('error', 'unknown')}")

        audio_b64 = meta.get("audio_b64")
        if not audio_b64:
            raise RuntimeError(f"{self.capability().name} runner returned no audio_b64")
        raw = base64.b64decode(audio_b64)
        audio = np.frombuffer(raw, dtype=np.float32).copy()
        sr = int(meta["sample_rate"])
        logger.info(
            "%s done in %.2fs (audio=%.2fs, RTF=%.2f)",
            self.capability().name,
            elapsed,
            len(audio) / sr,
            elapsed / max(len(audio) / sr, 1e-3),
        )
        return audio, sr

    # ---- Lifecycle hooks (subprocess mode: noop) ----

    def unload(self) -> None:
        """No-op for subprocess mode; runner spawns fresh each call."""
        pass

    def healthcheck(self) -> dict:
        py_ok = self.WSL_DISTRO is not None or os.path.exists(self.PYTHON)
        runner_ok = os.path.exists(self._runner_abs_path())
        return {
            "ok": py_ok and runner_ok,
            "engine": self.capability().name,
            "python_exists": py_ok,
            "runner_exists": runner_ok,
            "wsl": bool(self.WSL_DISTRO),
        }

    @abstractmethod
    def capability(self) -> EngineCapability: ...

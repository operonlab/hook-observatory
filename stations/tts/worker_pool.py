"""WorkerPool — station 端管理兩個常駐 worker daemon + global model_pool lock.

少爺 2026-05-19 規格:
- 兩個 worker (trio + qwen3) 各自 venv，常駐 keep-alive
- model_pool max=1：同時只允許 1 個 engine 載入 GPU (跨 worker 也是)
- idle_timeout=120s 自動 unload
- batch: 一次處理多句（同 engine 共用 keep-alive）

協議：JSONL over stdin/stdout，base_daemon.py 內定義.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SEC = float(os.environ.get("TTS_IDLE_TIMEOUT_SEC", "120"))
SWEEPER_INTERVAL_SEC = 30.0
WORKER_BOOT_TIMEOUT_SEC = 60.0
SYNTH_TIMEOUT_SEC = float(os.environ.get("TTS_SYNTH_TIMEOUT_SEC", "300"))


# Engine name → which worker hosts it
# - "trio"     : WSL cosyvoice_vllm venv (cosyvoice + vibevoice)
# - "indextts" : Windows native lab/indextts/.venv (indextts2 base + jmica)
# - "qwen3"    : WSL tts-qwen3 venv (qwen3tts_gpu)
_ENGINE_TO_WORKER: dict[str, str] = {
    "cosyvoice_v3_native": "trio",
    "cosyvoice_v3_vllm": "trio",
    "vibevoice": "trio",
    "indextts2_base": "indextts",
    "indextts2_jmica": "indextts",
    "qwen3tts_gpu": "qwen3",
}


@dataclass
class WorkerConfig:
    worker_id: str
    python: str
    script_path: str
    wsl_distro: str | None = None  # None → run native; else use wsl.exe -d <distro>
    extra_env: dict[str, str] = field(default_factory=dict)


# Default deployment paths (win-gpu)
DEFAULT_WORKERS = [
    WorkerConfig(
        worker_id="trio",
        python="/home/joneshong/.venvs/cosyvoice_vllm/bin/python3",
        script_path="/mnt/c/Users/User/workshop-station/stations/tts/workers/worker_trio_daemon.py",
        wsl_distro="Ubuntu",
    ),
    WorkerConfig(
        worker_id="indextts",
        python="C:/Users/User/workshop/lab/indextts/.venv/Scripts/python.exe",
        script_path="C:/Users/User/workshop-station/stations/tts/workers/worker_indextts_daemon.py",
        wsl_distro=None,  # Windows native, no WSL bridge
    ),
    WorkerConfig(
        worker_id="qwen3",
        python="/home/joneshong/.venvs/tts-qwen3/bin/python3",
        script_path="/mnt/c/Users/User/workshop-station/stations/tts/workers/worker_qwen3_daemon.py",
        wsl_distro="Ubuntu",
    ),
]


class WorkerHandle:
    """Manages one async subprocess + serialized command lock."""

    def __init__(self, cfg: WorkerConfig):
        self.cfg = cfg
        self.proc: asyncio.subprocess.Process | None = None
        self.cmd_lock = asyncio.Lock()
        self.supported: list[str] = []
        self.ready = False

    async def start(self) -> None:
        if self.cfg.wsl_distro:
            cmd = [
                "wsl.exe",
                "-d",
                self.cfg.wsl_distro,
                "--",
                self.cfg.python,
                self.cfg.script_path,
            ]
        else:
            cmd = [self.cfg.python, self.cfg.script_path]
        env = os.environ.copy()
        env.update(self.cfg.extra_env)
        logger.info("Spawning worker %s: %s", self.cfg.worker_id, " ".join(cmd))
        # NB: default StreamReader limit is 64KB — audio_b64 in synth response
        # can be 400KB+ (3s wav float32 base64). Raise to 64MB for safety.
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            limit=64 * 1024 * 1024,
        )
        # Read ready line
        try:
            line = await asyncio.wait_for(
                self.proc.stdout.readline(), timeout=WORKER_BOOT_TIMEOUT_SEC
            )
        except TimeoutError:
            raise RuntimeError(
                f"worker {self.cfg.worker_id} did not signal ready within {WORKER_BOOT_TIMEOUT_SEC}s"
            )
        try:
            data = json.loads(line.decode())
        except Exception as e:
            raise RuntimeError(f"worker {self.cfg.worker_id} bad ready signal: {line!r} ({e})")
        if not data.get("ready"):
            raise RuntimeError(f"worker {self.cfg.worker_id} not ready: {data}")
        self.supported = data.get("supported", [])
        self.ready = True
        logger.info("Worker %s ready, supports: %s", self.cfg.worker_id, self.supported)

    async def stop(self) -> None:
        if not self.proc:
            return
        try:
            await asyncio.wait_for(self.send({"op": "shutdown"}), timeout=10.0)
        except Exception:
            pass
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=5.0)
        except TimeoutError:
            self.proc.terminate()
        self.proc = None
        self.ready = False

    async def send(self, cmd: dict, timeout: float = SYNTH_TIMEOUT_SEC) -> dict:
        if not self.proc or not self.ready:
            raise RuntimeError(f"worker {self.cfg.worker_id} not running")
        async with self.cmd_lock:
            payload = (json.dumps(cmd, ensure_ascii=False) + "\n").encode()
            self.proc.stdin.write(payload)
            await self.proc.stdin.drain()
            try:
                line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=timeout)
            except TimeoutError:
                logger.warning(
                    "worker %s timeout on %s > %ss, force respawning",
                    self.cfg.worker_id,
                    cmd.get("op", "?"),
                    timeout,
                )
                await self._force_respawn()
                raise RuntimeError(
                    f"worker {self.cfg.worker_id} timeout on {cmd.get('op', '?')} > {timeout}s (respawned)"
                )
            if not line:
                err_tail = b""
                try:
                    err_tail = await asyncio.wait_for(self.proc.stderr.read(2000), timeout=1.0)
                except TimeoutError:
                    pass
                await self._force_respawn()
                raise RuntimeError(
                    f"worker {self.cfg.worker_id} died (respawned); stderr tail: {err_tail.decode(errors='replace')[-500:]}"
                )
            try:
                return json.loads(line.decode())
            except Exception as e:
                raise RuntimeError(f"worker {self.cfg.worker_id} bad response: {line!r} ({e})")

    async def _force_respawn(self) -> None:
        """Kill stuck worker subprocess and spawn fresh — for timeout recovery."""
        if self.proc:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5.0)
            except TimeoutError:
                pass
        self.proc = None
        self.ready = False
        try:
            await self.start()
        except Exception as e:
            logger.error("worker %s respawn failed: %s", self.cfg.worker_id, e)


class WorkerPool:
    """Single global model_pool with max=1 — swap engines across workers as needed."""

    def __init__(self, configs: list[WorkerConfig] | None = None):
        self.workers: dict[str, WorkerHandle] = {}
        for cfg in configs or DEFAULT_WORKERS:
            self.workers[cfg.worker_id] = WorkerHandle(cfg)
        self.active_engine: str | None = None
        self.active_worker_id: str | None = None
        self.last_used: float = 0.0
        self._lock = asyncio.Lock()
        self._sweeper_task: asyncio.Task | None = None

    async def start_all(self) -> None:
        """Spawn workers concurrently."""
        await asyncio.gather(*(w.start() for w in self.workers.values()))
        self._sweeper_task = asyncio.create_task(self._idle_sweeper_loop())

    async def stop_all(self) -> None:
        if self._sweeper_task:
            self._sweeper_task.cancel()
            try:
                await self._sweeper_task
            except (asyncio.CancelledError, BaseException):
                pass
        await asyncio.gather(*(w.stop() for w in self.workers.values()), return_exceptions=True)

    def _engine_to_worker(self, engine_name: str) -> str:
        wid = _ENGINE_TO_WORKER.get(engine_name)
        if wid is None:
            raise RuntimeError(f"unknown engine: {engine_name}")
        return wid

    async def _ensure_active(
        self, engine_name: str, load_kwargs: dict | None = None
    ) -> WorkerHandle:
        """Switch model_pool to `engine_name`. Returns the worker handle.

        Caller must hold self._lock.
        """
        target_wid = self._engine_to_worker(engine_name)
        target_worker = self.workers[target_wid]

        if self.active_engine == engine_name:
            return target_worker

        # Unload old (could be in different worker)
        if self.active_engine and self.active_worker_id:
            try:
                await self.workers[self.active_worker_id].send({"op": "unload"}, timeout=30.0)
            except Exception as e:
                logger.warning("unload old engine %s failed: %s", self.active_engine, e)

        # Load new — qwen3tts model load + first init 可超 240s，給寬鬆 timeout
        load_cmd = {"op": "load", "engine": engine_name}
        if load_kwargs:
            load_cmd.update(load_kwargs)
        load_resp = await target_worker.send(load_cmd, timeout=600.0)
        if not load_resp.get("ok"):
            raise RuntimeError(f"load {engine_name} failed: {load_resp.get('error', '?')}")

        self.active_engine = engine_name
        self.active_worker_id = target_wid
        return target_worker

    async def synth(
        self,
        engine_name: str,
        text: str,
        lang: str,
        voice_id: str = "master",
        speed: float = 1.0,
        ref_text: str | None = None,
        engine_specific: dict[str, Any] | None = None,
    ) -> dict:
        async with self._lock:
            worker = await self._ensure_active(engine_name)
            self.last_used = time.monotonic()
            # engine_specific keys (emotion/instruct/seed/...) flatten into the
            # synth command — base_daemon dispatches via _do_synth(**cmd) so the
            # extras reach engine-specific workers as kwargs. ref_text inside
            # engine_specific is honored only when the positional ref_text is
            # absent (positional path wins for backward compat).
            es = dict(engine_specific or {})
            es_ref_text = es.pop("ref_text", None)
            payload = {
                "op": "synth",
                "text": text,
                "lang": lang,
                "voice_id": voice_id,
                "speed": speed,
                "ref_text": ref_text if ref_text else (es_ref_text or ""),
                **es,
            }
            resp = await worker.send(payload)
            self.last_used = time.monotonic()
            return resp

    async def synth_batch(
        self,
        engine_name: str,
        items: list[dict[str, Any]],
    ) -> list[dict]:
        """Run multiple synth requests on the same engine — keep-alive between calls.

        Each item may carry an `engine_specific` dict; its keys flatten into the
        per-call command the same way `synth` does, letting long/podcast/batch
        endpoints attach per-segment emotion or instruct overrides.
        """
        async with self._lock:
            worker = await self._ensure_active(engine_name)
            results = []
            for it in items:
                self.last_used = time.monotonic()
                es = dict(it.get("engine_specific") or {})
                es_ref_text = es.pop("ref_text", None)
                ref_text_val = it.get("ref_text")
                payload = {
                    "op": "synth",
                    "text": it["text"],
                    "lang": it["lang"],
                    "voice_id": it.get("voice_id", "master"),
                    "speed": it.get("speed", 1.0),
                    "ref_text": ref_text_val if ref_text_val else (es_ref_text or ""),
                    **es,
                }
                resp = await worker.send(payload)
                results.append(resp)
                self.last_used = time.monotonic()
            return results

    async def status(self) -> dict:
        worker_status = {}
        for wid, w in self.workers.items():
            if w.proc and w.ready:
                try:
                    pong = await asyncio.wait_for(w.send({"op": "ping"}), timeout=5.0)
                    worker_status[wid] = {
                        "alive": True,
                        "loaded": pong.get("loaded"),
                        "supported": w.supported,
                    }
                except Exception as e:
                    worker_status[wid] = {"alive": False, "error": str(e)}
            else:
                worker_status[wid] = {"alive": False}
        idle = (time.monotonic() - self.last_used) if self.last_used else None
        return {
            "active_engine": self.active_engine,
            "active_worker": self.active_worker_id,
            "idle_sec": round(idle, 1) if idle is not None else None,
            "idle_timeout_sec": IDLE_TIMEOUT_SEC,
            "workers": worker_status,
        }

    async def _idle_sweeper_loop(self):
        while True:
            try:
                await asyncio.sleep(SWEEPER_INTERVAL_SEC)
            except asyncio.CancelledError:
                return
            if self.active_engine is None:
                continue
            if (time.monotonic() - self.last_used) < IDLE_TIMEOUT_SEC:
                continue
            async with self._lock:
                if self.active_engine and (time.monotonic() - self.last_used) >= IDLE_TIMEOUT_SEC:
                    logger.info("Idle timeout — unloading %s", self.active_engine)
                    try:
                        await self.workers[self.active_worker_id].send(
                            {"op": "unload"}, timeout=30.0
                        )
                    except Exception as e:
                        logger.warning("idle unload failed: %s", e)
                    self.active_engine = None
                    self.active_worker_id = None


def decode_synth_response(resp: dict) -> tuple[np.ndarray, int]:
    """Convert worker JSON response to (audio, sr)."""
    if not resp.get("ok"):
        raise RuntimeError(resp.get("error", "synth failed"))
    audio_b64 = resp.get("audio_b64")
    if not audio_b64:
        raise RuntimeError("response missing audio_b64")
    raw = base64.b64decode(audio_b64)
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    return audio, int(resp["sample_rate"])

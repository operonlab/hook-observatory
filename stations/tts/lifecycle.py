"""Lazy load + idle unload manager — shared single-GPU memory control.

對應 INTEGRATION-PLAN.md §「IndexTTS-2 base/jmica 雙實例策略」：
- 6 個 v3 engine 不能同時 keep alive（VRAM 累積會 OOM, 24GB 容不下）
- 採用 lazy load on demand + idle 60s 自動 unload
- 切語言 / 切引擎時觸發 swap，可預期 ~5s 載入 overhead
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base_v2 import TTSEngineV2

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SEC = 60  # 1min 後 unload；切引擎時若還在 idle 直接 unload


class LifecycleManager:
    """Track engine instances + last_used; periodic sweep unloads idle ones.

    Engines opt in by calling mark_used() before each synthesize, and exposing
    an `unload()` method (which tears down model + torch.cuda.empty_cache).
    """

    def __init__(self, idle_timeout: float = IDLE_TIMEOUT_SEC):
        self.idle_timeout = idle_timeout
        self._last_used: dict[str, float] = {}
        self._engines: dict[str, "TTSEngineV2"] = {}
        self._lock = threading.Lock()

    def register(self, name: str, engine: "TTSEngineV2") -> None:
        with self._lock:
            self._engines[name] = engine

    def mark_used(self, name: str) -> None:
        with self._lock:
            self._last_used[name] = time.monotonic()

    def is_idle(self, name: str) -> bool:
        last = self._last_used.get(name)
        if last is None:
            return False
        return (time.monotonic() - last) > self.idle_timeout

    def sweep(self) -> list[str]:
        """Unload all idle engines. Returns names unloaded."""
        unloaded = []
        with self._lock:
            candidates = [n for n, _ in self._engines.items() if self.is_idle(n)]
        for name in candidates:
            eng = self._engines.get(name)
            if eng is None:
                continue
            unload = getattr(eng, "unload", None)
            if not callable(unload):
                continue
            try:
                unload()
                unloaded.append(name)
                logger.info("Idle unload: %s", name)
            except Exception as e:
                logger.warning("Unload failed for %s: %s", name, e)
            with self._lock:
                self._last_used.pop(name, None)
        return unloaded

    def force_unload_all_except(self, keep: str | None = None) -> list[str]:
        """Swap mode — unload everything except `keep`. Used before loading a heavy engine."""
        unloaded = []
        with self._lock:
            names = [n for n in self._engines.keys() if n != keep]
        for name in names:
            eng = self._engines.get(name)
            unload = getattr(eng, "unload", None) if eng else None
            if not callable(unload):
                continue
            try:
                unload()
                unloaded.append(name)
            except Exception as e:
                logger.warning("Force unload failed for %s: %s", name, e)
            with self._lock:
                self._last_used.pop(name, None)
        return unloaded

    def status(self) -> dict:
        now = time.monotonic()
        with self._lock:
            return {
                name: {
                    "idle_sec": round(now - last, 1),
                    "will_unload_in": round(self.idle_timeout - (now - last), 1),
                }
                for name, last in self._last_used.items()
            }


# Module-level singleton
MANAGER = LifecycleManager()

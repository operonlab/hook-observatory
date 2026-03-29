"""TaskCompletion — Reactive Protocol 第七概念。

AsyncSubject 語意：exactly-once 完成信號，支援 late-subscriber replay。

用途：統一所有任務執行層（headless、tmux-relay、fleet）的完成通知。
Producer 呼叫 resolve/reject，Consumer 透過 subscribe 或 await wait() 取得結果。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from .reactive import Observer, Subscription

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Status literals
PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
TIMEOUT = "timeout"


@dataclass
class CompletionResult(Generic[T]):
    """Completion resolve/reject 的快取結果。"""

    value: T | None = None
    error: Exception | None = None
    completed_at: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


class TaskCompletion(Generic[T]):
    """Exactly-once completion signal with late-subscriber replay.

    Producer API:
        tc.mark_running()
        await tc.resolve(value)   # 或 await tc.reject(error)

    Consumer API:
        tc.subscribe(observer)    # Observer 三件組
        result = await tc.wait()  # 便利 await（可帶 timeout）
    """

    def __init__(self, task_id: str, *, metadata: dict[str, Any] | None = None) -> None:
        self._task_id = task_id
        self._metadata = metadata or {}
        self._status = PENDING
        self._result: CompletionResult[T] | None = None
        self._event = asyncio.Event()
        self._observers: list[Observer] = []
        self._created_at = time.time()

    # ── Properties ──

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def status(self) -> str:
        return self._status

    @property
    def metadata(self) -> dict[str, Any]:
        return self._metadata

    @property
    def is_terminal(self) -> bool:
        return self._status in (COMPLETED, FAILED, TIMEOUT)

    # ── Producer API ──

    def mark_running(self) -> None:
        if self._status == PENDING:
            self._status = RUNNING

    async def resolve(self, value: T) -> None:
        """發射成功結果。冪等——已終結時忽略。"""
        if self.is_terminal:
            return
        self._status = COMPLETED
        self._result = CompletionResult(value=value, completed_at=time.time())
        await self._notify_observers()
        self._event.set()

    async def reject(self, error: Exception) -> None:
        """發射失敗。冪等——已終結時忽略。"""
        if self.is_terminal:
            return
        self._status = FAILED
        self._result = CompletionResult(error=error, completed_at=time.time())
        await self._notify_observers()
        self._event.set()

    async def timeout(self) -> None:
        """標記超時。語意上等同 reject(TimeoutError)。"""
        if self.is_terminal:
            return
        self._status = TIMEOUT
        self._result = CompletionResult(
            error=TimeoutError(f"Task {self._task_id} timed out"),
            completed_at=time.time(),
        )
        await self._notify_observers()
        self._event.set()

    # ── Consumer API ──

    def subscribe(self, observer: Observer) -> Subscription:
        """訂閱完成信號。若已完成，立即 replay。"""
        sub = Subscription()

        if self.is_terminal and self._result is not None:
            # Late subscriber — 立即 replay
            task = asyncio.ensure_future(self._deliver(observer, self._result))
            sub.add(lambda: task.cancel() if not task.done() else None)
        else:
            self._observers.append(observer)
            sub.add(
                lambda: self._observers.remove(observer) if observer in self._observers else None
            )

        return sub

    async def wait(self, timeout: float | None = None) -> T:
        """便利方法：阻塞直到完成或超時。

        Raises:
            TimeoutError: 超過指定 timeout
            Exception: reject 時的原始錯誤
        """
        if not self.is_terminal:
            try:
                await asyncio.wait_for(self._event.wait(), timeout=timeout)
            except TimeoutError:
                await self.timeout()

        if self._result is None:
            raise RuntimeError(f"Task {self._task_id} has no result")

        if self._result.error is not None:
            raise self._result.error

        return self._result.value  # type: ignore[return-value]

    # ── Internal ──

    async def _notify_observers(self) -> None:
        if self._result is None:
            return
        for obs in list(self._observers):
            await self._deliver(obs, self._result)
        self._observers.clear()

    @staticmethod
    async def _deliver(observer: Observer, result: CompletionResult) -> None:
        try:
            if result.ok:
                await observer.on_next(result.value)
                await observer.on_complete()
            else:
                await observer.on_error(result.error)  # type: ignore[arg-type]
        except Exception:
            logger.exception("TaskCompletion observer delivery failed")

    def __repr__(self) -> str:
        elapsed = time.time() - self._created_at
        return f"TaskCompletion({self._task_id!r}, status={self._status}, elapsed={elapsed:.1f}s)"


class CompletionRegistry:
    """追蹤進行中的 TaskCompletion 實例，供 HTTP callback 查找。"""

    def __init__(self) -> None:
        self._completions: dict[str, TaskCompletion] = {}

    def register(self, tc: TaskCompletion) -> None:
        self._completions[tc.task_id] = tc

    def get(self, task_id: str) -> TaskCompletion | None:
        return self._completions.get(task_id)

    def remove(self, task_id: str) -> None:
        self._completions.pop(task_id, None)

    def cleanup_terminal(self) -> int:
        """清除已終結的 TaskCompletion。回傳清除數量。"""
        to_remove = [tid for tid, tc in self._completions.items() if tc.is_terminal]
        for tid in to_remove:
            del self._completions[tid]
        return len(to_remove)

    @property
    def active_count(self) -> int:
        return sum(1 for tc in self._completions.values() if not tc.is_terminal)

    def __len__(self) -> int:
        return len(self._completions)

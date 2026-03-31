"""Assistant service — Claude Code tmux persistent session.

Uses a dedicated tmux window with Claude Code (haiku) that has full
tool access: memvault recall, file reading, API calls, etc.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncGenerator, Generator

from src.shared.sse import BlockType, StreamBlock
from tmux_lib.cc_reader import iter_cc_response, resolve_session_jsonl, strip_cc_noise
from tmux_lib.cli_session import is_shell
from tmux_lib.primitives import send_enter, send_text, tmux_check, tmux_ok

logger = logging.getLogger(__name__)

# ── Config ──
TMUX_TARGET = "assistant"
_startup_lock = threading.Lock()
_PROMPT_FILE = "/tmp/assistant-system-prompt.txt"
SYSTEM_PROMPT = (
    "你是 Workshop 助手精靈。\n\n"
    "## 行為準則\n"
    "- 用繁體中文直接回答，稱呼使用者為「少爺」\n"
    "- 不反問、不列選項，直接給答案\n"
    "- 回覆 3-5 句，每句要有具體資訊\n"
    "- 需要即時資訊（天氣、新聞、價格等）時，主動用 WebSearch 查詢\n"
    "- 主動用 memvault recall 搜尋相關記憶來輔助回答\n"
    "- 語氣簡潔自信，像管家般貼心"
)
_CLAUDE_CMD = (
    "CLAUDE_VOICE=0 claude --dangerously-skip-permissions --model haiku"
    " --effort medium --max-turns 3"
    f' --system-prompt "$(cat {_PROMPT_FILE})"'
)
_POLL_INTERVAL = 0.3
_TIMEOUT = 180
_REDIS_LAST_USED_KEY = "assistant:haiku:last_used"
_WATCHDOG_TS_FILE = "/tmp/assistant_watchdog_ts"
_CHAT_LOG = "/tmp/assistant-chat.log"

_active_sessions: set[str] = set()


def _touch_assistant_last_used() -> None:
    """Update timestamp so assistant_watchdog.py knows we're active."""
    now = str(int(time.time()))
    try:
        with open(_WATCHDOG_TS_FILE, "w") as f:
            f.write(now)
    except OSError:
        pass
    try:
        import redis as _redis

        _redis.Redis(decode_responses=True).set(_REDIS_LAST_USED_KEY, now)
    except Exception:
        logger.warning("assistant: Redis keepalive write failed — watchdog relies on file fallback")


def _log_chat(
    *,
    session_id: str = "",
    prompt: str | None = None,
    response: str | None = None,
    duration_s: float = 0,
) -> None:
    """Append formatted Q&A to the chat log."""
    from datetime import datetime

    now = datetime.now().strftime("%H:%M:%S")
    sid = session_id[:12] if session_id else "—"

    with open(_CHAT_LOG, "a") as f:
        if sid not in _active_sessions and sid != "—":
            _active_sessions.add(sid)
            f.write(f"\n{'─' * 50}\n")
            f.write(f"  SESSION {sid}  started {now}\n")
            f.write(f"{'─' * 50}\n")
        if prompt is not None:
            f.write(f"\n  [{now}] 少爺\n")
            f.write(f"  {prompt}\n")
        if response is not None:
            f.write(f"\n  [{now}] 助手\n")
            for line in response.splitlines():
                f.write(f"  {line}\n")
            f.write(f"  ⏱ {duration_s:.1f}s\n")


def _ensure_assistant_window() -> bool:
    """Ensure tmux assistant window exists with Claude Code running."""
    if not _startup_lock.acquire(timeout=10):
        logger.warning("assistant: startup lock timeout — returning False")
        return False
    try:
        return _ensure_assistant_window_inner()
    finally:
        _startup_lock.release()


def _ensure_assistant_window_inner() -> bool:
    from tmux_lib.cli_session import wait_for_prompt
    from tmux_lib.patterns import CLAUDE_CODE

    windows = tmux_ok("list-windows", "-F", "#{window_name}")
    if windows is None:
        return False
    if TMUX_TARGET not in windows.split("\n"):
        try:
            tmux_check("new-window", "-n", TMUX_TARGET)
            time.sleep(1)
        except RuntimeError:
            return False
    if is_shell(TMUX_TARGET):
        with open(_PROMPT_FILE, "w") as f:
            f.write(SYSTEM_PROMPT)
        send_text(TMUX_TARGET, _CLAUDE_CMD, buf_name="_assistant_paste")
        time.sleep(0.15)
        send_enter(TMUX_TARGET)
        deadline = time.time() + 10
        while time.time() < deadline:
            if not is_shell(TMUX_TARGET):
                break
            time.sleep(0.5)
        else:
            return False
        if not wait_for_prompt(TMUX_TARGET, CLAUDE_CODE, timeout=30, poll_interval=0.3):
            return False
        time.sleep(1.0)
        logger.info("assistant: CC ready")
    return True


# ── Delta 串流核心 ──


class _DeltaEvent:
    """單次 delta 事件的資料容器。"""

    __slots__ = ("is_done", "text_delta", "tool_progress")

    def __init__(
        self,
        text_delta: str = "",
        tool_progress: str | None = None,
        is_done: bool = False,
    ) -> None:
        self.text_delta = text_delta
        self.tool_progress = tool_progress
        self.is_done = is_done


def _iter_chat(prompt: str, *, session_id: str = "") -> Generator[_DeltaEvent, None, None]:
    """Send prompt to persistent CC, read response via hybrid JSONL+stability."""
    from tmux_lib.cli_session import has_prompt, wait_for_prompt
    from tmux_lib.patterns import CLAUDE_CODE
    from tmux_lib.primitives import capture

    if not _ensure_assistant_window():
        yield _DeltaEvent(text_delta="助手服務暫時無法使用", is_done=True)
        return

    if not has_prompt(TMUX_TARGET, CLAUDE_CODE, lines=5):
        if not wait_for_prompt(TMUX_TARGET, CLAUDE_CODE, timeout=15, poll_interval=0.3):
            yield _DeltaEvent(text_delta="助手正在處理其他請求，請稍後再試", is_done=True)
            return

    _log_chat(session_id=session_id, prompt=prompt)
    t0 = time.time()

    # Discover JSONL + record baseline offset
    jsonl_path = resolve_session_jsonl(TMUX_TARGET)
    baseline_offset = 0
    if jsonl_path:
        try:
            baseline_offset = jsonl_path.stat().st_size
        except OSError:
            pass

    # Reset pane
    tmux_ok("send-keys", "-t", TMUX_TARGET, "-R")
    tmux_ok("clear-history", "-t", TMUX_TARGET)
    time.sleep(0.3)

    # Send prompt with retry
    user_q = prompt[-20:]
    visible = False
    for _attempt in range(1, 4):
        send_text(TMUX_TARGET, prompt, buf_name="_assistant_paste")
        time.sleep(0.15)
        send_enter(TMUX_TARGET)
        dl = time.time() + 5
        while time.time() < dl:
            time.sleep(0.3)
            cur = capture(TMUX_TARGET, start_line=-200, join_wrapped=True) or ""
            if user_q in cur:
                visible = True
                break
        if visible:
            break
        time.sleep(1.0)
    if not visible:
        yield _DeltaEvent(text_delta="助手沒有回應，請再試一次", is_done=True)
        return

    # Use shared hybrid reader
    full_text = ""
    sent_len = 0
    last_prog = None
    for delta in iter_cc_response(
        TMUX_TARGET,
        jsonl_path=jsonl_path,
        baseline_offset=baseline_offset,
        timeout=_TIMEOUT,
    ):
        if delta.text:
            cleaned = strip_cc_noise(delta.text)
            if cleaned:
                full_text += ("\n" if full_text else "") + cleaned
                if len(full_text) > sent_len:
                    yield _DeltaEvent(text_delta=full_text[sent_len:])
                    sent_len = len(full_text)
        if delta.tool_label and delta.tool_label != last_prog:
            last_prog = delta.tool_label
            yield _DeltaEvent(tool_progress=delta.tool_label)
        if delta.is_done:
            elapsed = time.time() - t0
            _log_chat(session_id=session_id, response=full_text, duration_s=elapsed)
            _touch_assistant_last_used()
            logger.info("assistant: done, %d chars, %.1fs", sent_len, elapsed)
            yield _DeltaEvent(is_done=True)
            return

    # Timeout
    elapsed = time.time() - t0
    if full_text and len(full_text) > sent_len:
        yield _DeltaEvent(text_delta=full_text[sent_len:])
        _log_chat(session_id=session_id, response=full_text, duration_s=elapsed)
    yield _DeltaEvent(is_done=True)


# ── Public async API ──
# Architectural note: TMUX_TARGET is a single shared tmux window. All requests
# are serialized via _lock to prevent cross-request pollution. _REQUEST_QUEUE
# provides bounded overflow protection: at most 5 pending requests; excess
# requests are fast-failed immediately. Per-request windows would improve
# isolation further but add complexity; acceptable for solo-dev use.
_lock = asyncio.Lock()
_REQUEST_QUEUE: asyncio.Queue[tuple] = asyncio.Queue(maxsize=5)


async def stream_chat(
    messages: list[dict], *, session_id: str | None = None
) -> AsyncGenerator[StreamBlock, None]:
    """Stream CC one-shot response as SSE events."""
    # Fast-fail if queue is full (> 5 pending requests)
    if _REQUEST_QUEUE.full():
        yield StreamBlock(type=BlockType.ERROR, data={"message": "助手請求佇列已滿，請稍後再試"})
        return

    yield StreamBlock(type=BlockType.THINKING, data={"message": "思考中..."})

    user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
    if not user_msg:
        yield StreamBlock(type=BlockType.ERROR, data={"message": "沒有收到問題"})
        return

    prompt = user_msg.replace(chr(10), " ")
    sid = session_id or ""

    queue: asyncio.Queue[_DeltaEvent | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _run_iter():
        try:
            for event in _iter_chat(prompt, session_id=sid):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception:
            logger.error("assistant: _iter_chat error", exc_info=True)
            # 確保 consumer 能結束
            loop.call_soon_threadsafe(
                queue.put_nowait, _DeltaEvent(text_delta="助手回應時發生錯誤", is_done=True)
            )
        finally:
            # None 作為結束信號
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async with _lock:
        # 在背景線程啟動 blocking generator
        asyncio.get_event_loop().run_in_executor(None, _run_iter)

        has_content = False

        while True:
            event = await queue.get()

            # None = thread 結束
            if event is None:
                break

            # 工具進度 → PROGRESS block
            if event.tool_progress:
                yield StreamBlock(
                    type=BlockType.PROGRESS,
                    data={"message": event.tool_progress},
                )

            # 新增文字 → CONTENT delta block
            if event.text_delta:
                has_content = True
                yield StreamBlock(
                    type=BlockType.CONTENT,
                    data={"text": event.text_delta, "is_delta": True},
                )

            # 完成信號 → 跳出迴圈（等 None 確認 thread 結束）
            if event.is_done:
                # 若完全沒有內容，補一個空回應提示
                if not has_content:
                    yield StreamBlock(
                        type=BlockType.CONTENT,
                        data={"text": "（助手回應為空）", "is_delta": False},
                    )
                # 繼續消耗 queue 直到收到 None
                continue

    yield StreamBlock(type=BlockType.DONE, data={})

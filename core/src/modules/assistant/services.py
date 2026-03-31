"""Assistant service — Claude Code one-shot subprocess.

Runs `claude -p --output-format stream-json` per request, reads structured
JSON from stdout. No tmux capture-pane parsing needed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Generator

from src.shared.sse import BlockType, StreamBlock

logger = logging.getLogger(__name__)

# ── Config ──
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
_REDIS_LAST_USED_KEY = "assistant:haiku:last_used"
_CHAT_LOG = "/tmp/assistant-chat.log"


_active_sessions: set[str] = set()


def _log_chat(
    *,
    session_id: str = "",
    event: str = "qa",
    prompt: str | None = None,
    response: str | None = None,
    duration_s: float = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Append formatted entry to the chat log."""
    from datetime import datetime

    now = datetime.now().strftime("%H:%M:%S")
    sid = session_id[:12] if session_id else "—"

    with open(_CHAT_LOG, "a") as f:
        if event == "qa" and sid not in _active_sessions and sid != "—":
            _active_sessions.add(sid)
            f.write(f"\n{'─' * 50}\n")
            f.write(f"  SESSION {sid}  started {now}\n")
            f.write(f"{'─' * 50}\n")

        if event == "qa":
            if prompt is not None:
                f.write(f"\n  [{now}] 少爺\n")
                f.write(f"  {prompt}\n")
            if response is not None:
                f.write(f"\n  [{now}] 助手\n")
                for line in response.splitlines():
                    f.write(f"  {line}\n")
                parts = [f"⏱ {duration_s:.1f}s"]
                if input_tokens or output_tokens:
                    parts.append(f"📊 {input_tokens}in/{output_tokens}out")
                f.write(f"  {'  '.join(parts)}\n")

        elif event == "end":
            _active_sessions.discard(sid)
            f.write(f"\n{'─' * 50}\n")
            f.write(f"  SESSION {sid}  ended {now}\n")
            f.write(f"{'─' * 50}\n\n")


def _strip_sources(text: str) -> str:
    """Remove trailing Sources/References section from CC response text."""
    for marker in ("\nSources:", "\nSource:", "\nReferences:", "\nLearn more:"):
        idx = text.find(marker)
        if idx > 0:
            return text[:idx].rstrip()
    return text


# ── Streaming core ──


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
    """One-shot CC subprocess with stream-json + log file visibility."""
    import json
    import os
    import subprocess

    cmd = [
        "claude",
        "-p",
        prompt,
        "--dangerously-skip-permissions",
        "--model",
        "haiku",
        "--effort",
        "medium",
        "--max-turns",
        "3",
        "--output-format",
        "stream-json",
        "--verbose",
        "--system-prompt",
        SYSTEM_PROMPT,
    ]
    env = {**os.environ, "CLAUDE_VOICE": "0"}
    env.pop("CLAUDECODE", None)

    _log_chat(session_id=session_id, prompt=prompt)
    t0 = time.time()

    logger.info("assistant: starting CC subprocess sid=%s", session_id)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    except FileNotFoundError:
        yield _DeltaEvent(text_delta="助手服務暫時無法使用（claude 未安裝）", is_done=True)
        return

    collected_text: list[str] = []

    try:
        for raw_line in proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = ev.get("type")

            if etype == "assistant":
                for block in ev.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            text = _strip_sources(text)
                        if text:
                            collected_text.append(text)
                            yield _DeltaEvent(text_delta=text)

            elif etype == "result":
                elapsed = time.time() - t0
                usage = ev.get("usage", {})
                in_tok = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                out_tok = usage.get("output_tokens", 0)
                if ev.get("is_error"):
                    err = ev.get("error", "未知錯誤")
                    _log_chat(session_id=session_id, response=f"[ERROR] {err}", duration_s=elapsed)
                    yield _DeltaEvent(text_delta=f"助手回應時發生錯誤：{err}", is_done=True)
                else:
                    try:
                        import redis as _redis

                        r = _redis.Redis(decode_responses=True)
                        r.set(_REDIS_LAST_USED_KEY, str(int(time.time())))
                    except Exception:
                        pass
                    cost = ev.get("total_cost_usd", 0)
                    turns = ev.get("num_turns", 0)
                    logger.info(
                        "assistant: done sid=%s cost=$%.4f turns=%d", session_id, cost, turns
                    )
                    _log_chat(
                        session_id=session_id,
                        response="".join(collected_text),
                        duration_s=elapsed,
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                    )
                yield _DeltaEvent(is_done=True)
                return

        proc.wait(timeout=5)
        if proc.returncode != 0:
            stderr = (proc.stderr.read() or "").strip()[:200]
            logger.warning("assistant: CC exited %d: %s", proc.returncode, stderr)
            yield _DeltaEvent(text_delta="助手回應時發生錯誤", is_done=True)
        else:
            yield _DeltaEvent(is_done=True)

    except Exception:
        logger.error("assistant: subprocess error", exc_info=True)
        yield _DeltaEvent(text_delta="助手回應時發生錯誤", is_done=True)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


# ── Public async API ──

_lock = asyncio.Lock()


async def stream_chat(
    messages: list[dict], *, session_id: str | None = None
) -> AsyncGenerator[StreamBlock, None]:
    """Stream CC one-shot response as SSE events."""
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

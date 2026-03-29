"""Assistant service — Claude Code tmux persistent session.

Uses a dedicated tmux window with Claude Code (haiku) that has full
tool access: memvault recall, file reading, API calls, etc.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Generator

from src.shared.sse import BlockType, StreamBlock
from tmux_lib.cli_session import has_prompt, is_shell, wait_for_prompt
from tmux_lib.patterns import CLAUDE_CODE
from tmux_lib.primitives import capture, send_enter, send_text, tmux_check, tmux_ok

logger = logging.getLogger(__name__)

# ── Config ──
TMUX_TARGET = "assistant"
_PROMPT_FILE = "/tmp/assistant-system-prompt.txt"
SYSTEM_PROMPT = (
    "你是 Workshop 助手精靈。\n\n"
    "## 行為準則\n"
    "- 用繁體中文直接回答，稱呼使用者為「少爺」\n"
    "- 不反問、不列選項，直接給答案\n"
    "- 回覆 3-5 句，每句要有具體資訊\n"
    "- 主動用 memvault recall 搜尋相關記憶來輔助回答\n"
    "- 語氣簡潔自信，像管家般貼心"
)
_CLAUDE_CMD = (
    "CLAUDE_VOICE=0 claude --dangerously-skip-permissions --model haiku"
    f' --system-prompt "$(cat {_PROMPT_FILE})"'
)
_POLL_INTERVAL = 0.3  # 縮短 polling 間隔：0.8s → 0.3s，讓 delta 更即時
_TIMEOUT = 90
_REDIS_LAST_USED_KEY = "assistant:haiku:last_used"


def _ensure_assistant_window() -> bool:
    """Ensure tmux assistant window exists with Claude Code running."""
    windows = tmux_ok("list-windows", "-F", "#{window_name}")
    if windows is None:
        logger.warning("assistant: tmux not available")
        return False

    if TMUX_TARGET not in windows.split("\n"):
        logger.info("assistant: creating window")
        try:
            tmux_check("new-window", "-n", TMUX_TARGET)
            time.sleep(1)
        except RuntimeError:
            logger.warning("assistant: failed to create window")
            return False

    if is_shell(TMUX_TARGET):
        logger.info("assistant: starting Claude Code")
        with open(_PROMPT_FILE, "w") as f:
            f.write(SYSTEM_PROMPT)
        send_text(TMUX_TARGET, _CLAUDE_CMD, buf_name="_assistant_paste")
        send_enter(TMUX_TARGET)
        if not wait_for_prompt(TMUX_TARGET, CLAUDE_CODE, timeout=30, poll_interval=0.3):
            logger.warning("assistant: Claude Code failed to start within 30s")
            return False
        logger.info("assistant: Claude Code ready")

    return True


def _is_ui_chrome(line: str) -> bool:
    """判斷某行是否為 Claude Code UI chrome（非使用者可見內容）。"""
    s = line.strip()
    if not s:
        return False
    # Prompt 提示符
    if s.startswith("❯"):
        return True
    # 狀態列 emoji
    if any(c in s for c in ("🔖", "📁", "⎇", "🤖", "💰", "✍️", "⏵")):
        return True
    if "bypass" in s.lower() and "permission" in s.lower():
        return True
    if "shift+tab" in s.lower() or "tab to cycle" in s.lower():
        return True
    # 分隔線
    if s.count("─") > 10:
        return True
    # 處理中指示符（✻ Crunched, ✳ Reticulating, ✶ Bunning 等）
    if s.startswith(("✻", "✳", "✶")):
        return True
    # Claude Code 橫幅 / pig logo
    if "Claude Code" in s or s.startswith("▐") or s.startswith("▝") or s.startswith("▘"):
        return True
    return False


def _is_tool_block(line: str) -> bool:
    """判斷 ⏺ 行是否為工具呼叫（非文字內容）。"""
    s = line.strip()
    if not s.startswith("⏺"):
        return False
    after = s[2:].strip()
    # 工具呼叫模式：Bash(...), Read(...), Skill(...), Write(...) 等
    tool_patterns = (
        "Bash(",
        "Read(",
        "Write(",
        "Edit(",
        "Grep(",
        "Glob(",
        "Skill(",
        "Agent(",
        "Task",
        "Search(",
        "WebFetch(",
    )
    return any(after.startswith(p) for p in tool_patterns)


def _extract_tool_progress(line: str) -> str | None:
    """從工具呼叫行擷取進度描述，回傳人類可讀的簡短說明。

    例如 `⏺ Bash(python3 scripts/…)` → `執行指令中…`
    回傳 None 表示不是工具呼叫或無法識別。
    """
    s = line.strip()
    if not s.startswith("⏺"):
        return None
    after = s[2:].strip()
    # 對應工具名稱到友善說明
    tool_labels = {
        "Bash(": "執行指令中…",
        "Read(": "讀取檔案中…",
        "Write(": "寫入檔案中…",
        "Edit(": "修改檔案中…",
        "Grep(": "搜尋內容中…",
        "Glob(": "搜尋檔案中…",
        "Skill(": "呼叫技能中…",
        "Agent(": "呼叫 Agent 中…",
        "Task": "執行任務中…",
        "Search(": "搜尋中…",
        "WebFetch(": "擷取網頁中…",
    }
    for pattern, label in tool_labels.items():
        if after.startswith(pattern):
            return label
    return None


def _extract_response(before: str, after: str) -> str:
    """從 pane 內容擷取 Claude 最後的文字回應。

    使用 -J 旗標時，每行都是完整的邏輯行（無自動換行分割）。
    策略：
    1. 找最後一個有文字的 ❯ 行（使用者輸入行）
    2. 收集提示行到下一個空白 ❯ 之間的行
    3. 只保留 ⏺ 文字行（跳過工具呼叫、工具輸出、UI chrome）
    """
    lines = after.strip().splitlines()

    # 1. 找最後一個提示行（❯ 後有實際文字）
    prompt_idx = -1
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("❯") and len(s) > 2:
            prompt_idx = i

    if prompt_idx == -1:
        return ""

    # 2. 找結尾 ❯（回應後的空白提示符）
    end_idx = len(lines)
    for i in range(prompt_idx + 1, len(lines)):
        s = lines[i].strip()
        # 空白 ❯ 提示符或 ❯ 接下一個提示 = 結束
        if s == "❯" or (s.startswith("❯") and s != lines[prompt_idx].strip()):
            end_idx = i
            break

    response_lines = lines[prompt_idx + 1 : end_idx]

    # 3. 擷取文字 — 只保留 ⏺ 文字行（非工具呼叫）
    result = []
    for line in response_lines:
        s = line.strip()
        if not s:
            continue

        # 跳過所有 UI chrome
        if _is_ui_chrome(line):
            continue

        # 跳過工具呼叫（⏺ Bash(...), ⏺ Skill(...) 等）
        if _is_tool_block(line):
            continue

        # 跳過工具輸出（⎿ ...）及折疊（… +N lines）
        if s.startswith("⎿") or s.startswith("…"):
            continue

        # ⏺ 文字行 = 實際回應
        if s.startswith("⏺"):
            text = s[len("⏺") :].strip()
            if text:
                result.append(text)
            continue

        # 縮排的連續內容（如編號列表）
        if result and s and not s.startswith(("⏺", "⎿", "…", "❯")):
            result.append(s)

    return "\n".join(result).strip()


# ── Delta 擷取輔助 ──


def _extract_visible_lines_after_prompt(
    pane_content: str, prompt_idx_hint: int | None = None
) -> tuple[list[str], int]:
    """從 pane 內容中擷取提示行後的所有可見行。

    回傳 (lines_after_prompt, prompt_idx)，若找不到提示行則 prompt_idx = -1。
    """
    lines = pane_content.strip().splitlines()
    prompt_idx = -1
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("❯") and len(s) > 2:
            prompt_idx = i
    if prompt_idx == -1:
        return [], -1
    return lines[prompt_idx + 1 :], prompt_idx


def _parse_delta_lines(lines: list[str]) -> tuple[str, str | None]:
    """解析提示後的行，分離文字內容與最後一個工具進度。

    回傳 (accumulated_text, tool_progress_or_None)。
    tool_progress 是最後一個工具呼叫行的友善說明（若目前正在使用工具）。
    """
    text_parts: list[str] = []
    last_tool_progress: str | None = None

    for line in lines:
        s = line.strip()
        if not s:
            continue

        if _is_ui_chrome(line):
            continue

        if s.startswith("⎿") or s.startswith("…"):
            continue

        # 工具呼叫 → 更新進度標籤，不納入文字
        if _is_tool_block(line):
            progress = _extract_tool_progress(line)
            if progress:
                last_tool_progress = progress
            continue

        # ⏺ 文字行
        if s.startswith("⏺"):
            text = s[len("⏺") :].strip()
            if text:
                text_parts.append(text)
                last_tool_progress = None  # 有新文字，清除工具進度
            continue

        # 縮排連續內容
        if text_parts and s and not s.startswith(("⏺", "⎿", "…", "❯")):
            text_parts.append(s)
            last_tool_progress = None

    return "\n".join(text_parts).strip(), last_tool_progress


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


def _iter_chat(prompt: str) -> Generator[_DeltaEvent, None, None]:
    """阻塞 generator：送出 prompt 後，每次 pane 有新內容就 yield delta。

    這是 delta 串流的核心：不等全部回應完成，而是邊 polling 邊 yield。
    若解析過程出現問題，會 yield is_done=True 並附上 fallback 全量文字。
    """
    if not _ensure_assistant_window():
        yield _DeltaEvent(text_delta="助手服務暫時無法使用（tmux 視窗啟動失敗）", is_done=True)
        return

    if not has_prompt(TMUX_TARGET, CLAUDE_CODE, lines=5):
        logger.info("assistant: waiting for ready...")
        if not wait_for_prompt(TMUX_TARGET, CLAUDE_CODE, timeout=15, poll_interval=0.3):
            yield _DeltaEvent(text_delta="助手正在處理其他請求，請稍後再試", is_done=True)
            return

    # 清掉 scrollback history，避免歷史 ❯ 干擾完成偵測
    tmux_ok("clear-history", "-t", TMUX_TARGET)
    time.sleep(0.2)

    # 記錄送出前的 pane 狀態
    before = capture(TMUX_TARGET, start_line=-200, join_wrapped=True) or ""
    import sys

    print(
        f"[ASSISTANT DEBUG] before capture: {len(before)} chars, {len(before.splitlines())} lines",
        file=sys.stderr,
        flush=True,
    )
    send_text(TMUX_TARGET, prompt, buf_name="_assistant_paste")
    send_enter(TMUX_TARGET)

    # 從 prompt 裡提取使用者問題作為識別標記
    user_question = prompt[-20:]

    # 等待我們的 prompt 出現在 pane 裡（而非只等 content change）
    deadline = time.time() + _TIMEOUT
    our_prompt_visible = False
    while time.time() < deadline:
        time.sleep(0.3)
        current = capture(TMUX_TARGET, start_line=-200, join_wrapped=True) or ""
        if user_question in current and current != before:
            our_prompt_visible = True
            print(
                f"[ASSISTANT DEBUG] our prompt visible, q='{user_question}'",
                file=sys.stderr,
                flush=True,
            )
            break
    if not our_prompt_visible:
        yield _DeltaEvent(text_delta="助手沒有回應，請再試一次", is_done=True)
        return

    # 再等一下讓 Claude Code 開始處理（跳過 prompt 剛出現但還沒回應的階段）
    time.sleep(1.0)

    # ── delta 追蹤狀態 ──
    sent_text_len = 0  # 已 yield 的累積文字長度
    last_tool_progress: str | None = None  # 上一次傳送的工具進度（避免重複）

    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)
        try:
            current = capture(TMUX_TARGET, start_line=-200, join_wrapped=True) or ""
        except Exception:
            logger.warning("assistant: capture failed in delta loop", exc_info=True)
            # graceful degradation：直接跳到全量模式
            break

        lines_after, prompt_idx = _extract_visible_lines_after_prompt(current)

        if prompt_idx == -1:
            # 還沒找到我們的提示行，繼續等
            logger.debug("assistant: prompt not found yet in pane")
            continue

        print(
            f"[ASSISTANT DEBUG] prompt@{prompt_idx}, {len(lines_after)} lines after, tail: {[l.strip()[:30] for l in lines_after[-3:]]}",
            file=sys.stderr,
            flush=True,
        )

        try:
            accumulated_text, tool_progress = _parse_delta_lines(lines_after)
        except Exception:
            logger.warning("assistant: _parse_delta_lines failed", exc_info=True)
            continue

        # ── 推送新增文字 delta ──
        if len(accumulated_text) > sent_text_len:
            new_text = accumulated_text[sent_text_len:]
            sent_text_len = len(accumulated_text)
            yield _DeltaEvent(text_delta=new_text)

        # ── 推送工具進度（若有變化）──
        if tool_progress and tool_progress != last_tool_progress:
            last_tool_progress = tool_progress
            yield _DeltaEvent(tool_progress=tool_progress)

        # ── 檢查是否已完成（❯ 提示符重新出現）──
        # 條件：1) 有回應內容 2) lines_after 最後幾行有空 ❯
        is_done = False
        has_response = len(accumulated_text) > 0
        if has_response:
            tail_lines = lines_after[-5:] if len(lines_after) > 5 else lines_after
            for line in tail_lines:
                s = line.strip()
                if s == "❯":
                    is_done = True
                    print(
                        f"[ASSISTANT DEBUG] DONE! text={len(accumulated_text)} chars",
                        file=sys.stderr,
                        flush=True,
                    )
                    break

        if is_done:
            # 更新 Redis last_used timestamp
            try:
                import redis as _redis

                r = _redis.Redis(decode_responses=True)
                r.set(_REDIS_LAST_USED_KEY, str(int(time.time())))
            except Exception:
                pass

            logger.info("assistant: delta stream done, total text %d chars", sent_text_len)
            yield _DeltaEvent(is_done=True)
            return

    # ── Timeout fallback：嘗試擷取現有內容 ──
    logger.warning("assistant: timed out waiting for response (%ds)", _TIMEOUT)
    try:
        current = capture(TMUX_TARGET, start_line=-200, join_wrapped=True) or ""
        fallback = _extract_response(before, current)
    except Exception:
        fallback = ""

    if fallback and len(fallback) > sent_text_len:
        # 補送尚未送出的部分
        yield _DeltaEvent(text_delta=fallback[sent_text_len:])

    yield _DeltaEvent(is_done=True)


# ── Public async API ──

_lock = asyncio.Lock()


async def stream_chat(messages: list[dict]) -> AsyncGenerator[StreamBlock, None]:
    """以 delta 方式串流 Claude Code tmux session 的回應。

    改為 delta 模式：每次 pane 有新內容就立即 yield CONTENT delta block，
    而非等全部完成後才送出整段回應。
    """
    yield StreamBlock(type=BlockType.THINKING, data={"message": "思考中..."})

    # 擷取使用者訊息
    user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
    if not user_msg:
        yield StreamBlock(type=BlockType.ERROR, data={"message": "沒有收到問題"})
        return

    # 指令已移至 --system-prompt，這裡只送使用者訊息
    prompt = user_msg.replace(chr(10), " ")

    # 使用 queue 橋接 sync generator 與 async generator
    queue: asyncio.Queue[_DeltaEvent | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _run_iter():
        """在 thread 中執行 _iter_chat，把 delta 事件放進 queue。"""
        try:
            for event in _iter_chat(prompt):
                # 線程安全地把事件推入 async queue
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

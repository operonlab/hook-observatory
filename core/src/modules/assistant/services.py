"""Assistant service — Claude Code tmux persistent session.

Uses a dedicated tmux window with Claude Code (haiku) that has full
tool access: memvault recall, file reading, API calls, etc.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncGenerator, Generator
from enum import StrEnum

from src.shared.sse import BlockType, StreamBlock
from tmux_lib.cli_session import is_shell
from tmux_lib.primitives import send_enter, send_text, tmux_check, tmux_ok

logger = logging.getLogger(__name__)

import threading

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
    " --effort low --max-turns 3"
    f' --system-prompt "$(cat {_PROMPT_FILE})"'
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
    """Append formatted entry to the chat log (visible via tail -f in tmux)."""
    from datetime import datetime

    now = datetime.now().strftime("%H:%M:%S")
    sid = session_id[:12] if session_id else "—"

    with open(_CHAT_LOG, "a") as f:
        # Auto-emit session start on first QA for a new session_id
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


def _ensure_log_tail() -> None:
    """Ensure tmux assistant pane runs tail -f on the chat log (best-effort)."""
    try:
        import pathlib

        pathlib.Path(_CHAT_LOG).touch(exist_ok=True)
        windows = tmux_ok("list-windows", "-F", "#{window_name}")
        if windows is None:
            return
        if TMUX_TARGET not in (windows or "").split("\n"):
            tmux_check("new-window", "-n", TMUX_TARGET)
            time.sleep(0.5)
        if is_shell(TMUX_TARGET):
            send_text(TMUX_TARGET, f"tail -f {_CHAT_LOG}")
            time.sleep(0.1)
            send_enter(TMUX_TARGET)
    except Exception:
        logger.debug("assistant: failed to setup log tail", exc_info=True)


# ── FSM Parser ──────────────────────────────────────────────────────────────
#
# CC output parsing 用 FSM 管理狀態，避免 hardcoded pattern list 追不上新工具。
# States: IDLE → CONTENT / TOOL → SOURCES (absorbing terminal)
# Events: 每行分類為一個 _LineKind，transition table 決定行為。


class _ParsePhase(StrEnum):
    IDLE = "idle"
    CONTENT = "content"
    TOOL = "tool"
    SOURCES = "sources"


class _LineKind(StrEnum):
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_OUTPUT = "tool_output"
    SOURCES_HEADING = "sources_heading"
    CONTINUATION = "continuation"
    DONE = "done"
    CHROME = "chrome"
    SKIP = "skip"


# (current_phase, event) → (next_phase, action)
# action: "emit" = append to text, "progress" = update tool label, "" = skip
_TRANSITIONS: dict[tuple[_ParsePhase, _LineKind], tuple[_ParsePhase, str]] = {
    # IDLE
    (_ParsePhase.IDLE, _LineKind.TEXT): (_ParsePhase.CONTENT, "emit"),
    (_ParsePhase.IDLE, _LineKind.TOOL_CALL): (_ParsePhase.TOOL, "progress"),
    (_ParsePhase.IDLE, _LineKind.TOOL_OUTPUT): (_ParsePhase.IDLE, ""),
    (_ParsePhase.IDLE, _LineKind.CONTINUATION): (_ParsePhase.IDLE, ""),
    (_ParsePhase.IDLE, _LineKind.SOURCES_HEADING): (_ParsePhase.SOURCES, ""),
    (_ParsePhase.IDLE, _LineKind.DONE): (_ParsePhase.IDLE, ""),
    # CONTENT
    (_ParsePhase.CONTENT, _LineKind.TEXT): (_ParsePhase.CONTENT, "emit"),
    (_ParsePhase.CONTENT, _LineKind.CONTINUATION): (_ParsePhase.CONTENT, "emit"),
    (_ParsePhase.CONTENT, _LineKind.TOOL_CALL): (_ParsePhase.TOOL, "progress"),
    (_ParsePhase.CONTENT, _LineKind.TOOL_OUTPUT): (_ParsePhase.CONTENT, ""),
    (_ParsePhase.CONTENT, _LineKind.SOURCES_HEADING): (_ParsePhase.SOURCES, ""),
    (_ParsePhase.CONTENT, _LineKind.DONE): (_ParsePhase.IDLE, ""),
    # TOOL
    (_ParsePhase.TOOL, _LineKind.TOOL_CALL): (_ParsePhase.TOOL, "progress"),
    (_ParsePhase.TOOL, _LineKind.TOOL_OUTPUT): (_ParsePhase.TOOL, ""),
    (_ParsePhase.TOOL, _LineKind.CONTINUATION): (_ParsePhase.TOOL, ""),
    (_ParsePhase.TOOL, _LineKind.TEXT): (_ParsePhase.CONTENT, "emit"),
    (_ParsePhase.TOOL, _LineKind.SOURCES_HEADING): (_ParsePhase.SOURCES, ""),
    (_ParsePhase.TOOL, _LineKind.DONE): (_ParsePhase.IDLE, ""),
    # SOURCES — absorbing: handled by early-continue in loop, no entries needed
}

# Regex: any identifier (with spaces/dots/underscores) followed by "("
# Covers: Bash(, Web Search(, mcp__foo__bar(, ToolSearch(, etc.
_TOOL_CALL_RE = re.compile(r"^(?:[A-Za-z_][\w. ]*\(|Task(?:\s|$|·))")

# Processing suffix: "· Architecting... (thinking with high effort)"
_PROCESSING_SUFFIX_RE = re.compile(
    r"\s+·\s+(?:Thinking|Architecting|Processing|Osmosing|Crunching|"
    r"Deciphering|Reticulating|Bunning|Iterating|Reflecting|Analyzing).*$",
    re.IGNORECASE,
)

# Sources / References heading on its own line
_SOURCES_HEADING_RE = re.compile(r"^\s*(?:Sources?|References?|Learn more)\s*:\s*$", re.IGNORECASE)


def _strip_sources(text: str) -> str:
    """Remove trailing Sources/References section from CC response text."""
    for marker in ("\nSources:", "\nSource:", "\nReferences:", "\nLearn more:"):
        idx = text.find(marker)
        if idx > 0:  # only strip if there's content before it
            return text[:idx].rstrip()
    return text


# Tool name → friendly progress label (regex-based)
_TOOL_LABEL_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^Bash\("), "執行指令中…"),
    (re.compile(r"^Read\("), "讀取檔案中…"),
    (re.compile(r"^Write\("), "寫入檔案中…"),
    (re.compile(r"^Edit\("), "修改檔案中…"),
    (re.compile(r"^Grep\("), "搜尋內容中…"),
    (re.compile(r"^Glob\("), "搜尋檔案中…"),
    (re.compile(r"^Skill\("), "呼叫技能中…"),
    (re.compile(r"^Agent\("), "呼叫 Agent 中…"),
    (re.compile(r"^Task"), "執行任務中…"),
    (re.compile(r"^(?:Web\s*Search|Search)\("), "搜尋中…"),
    (re.compile(r"^(?:Web\s*Fetch|WebFetch)\("), "擷取網頁中…"),
    (re.compile(r"^ToolSearch\("), "搜尋工具中…"),
    (re.compile(r"^mcp__"), "呼叫外部工具中…"),
]


# ── Low-level helpers ───────────────────────────────────────────────────────


def _is_ui_chrome(line: str) -> bool:
    """判斷某行是否為 Claude Code UI chrome（非使用者可見內容）。"""
    s = line.strip()
    if not s:
        return False
    if s.startswith("❯"):
        return True
    if any(c in s for c in ("🔖", "📁", "⎇", "🤖", "💰", "✍️", "⏵")):
        return True
    if "bypass" in s.lower() and "permission" in s.lower():
        return True
    if "shift+tab" in s.lower() or "tab to cycle" in s.lower():
        return True
    if s.count("─") > 10:
        return True
    # 處理中指示符（✻ ✳ ✶ + 獨立 · 行）
    if s.startswith(("✻", "✳", "✶", "·")):
        return True
    if "Claude Code" in s or s.startswith("▐") or s.startswith("▝") or s.startswith("▘"):
        return True
    return False


def _is_tool_block(line: str) -> bool:
    """判斷 ⏺ 行是否為工具呼叫（非文字內容）。"""
    s = line.strip()
    if not s.startswith("⏺"):
        return False
    after = s[2:].strip()
    return bool(_TOOL_CALL_RE.match(after))


def _strip_processing_suffix(text: str) -> str:
    """Remove CC processing indicator suffix (e.g. '· Architecting...')."""
    return _PROCESSING_SUFFIX_RE.sub("", text)


def _extract_tool_progress(line: str) -> str | None:
    """從工具呼叫行擷取進度描述。回傳人類可讀的簡短說明，或 None。"""
    s = line.strip()
    if not s.startswith("⏺"):
        return None
    after = s[2:].strip()
    after = _strip_processing_suffix(after)
    for pattern, label in _TOOL_LABEL_MAP:
        if pattern.match(after):
            return label
    # Fallback: regex 確認是工具呼叫但無對應 label
    if _TOOL_CALL_RE.match(after):
        return "處理中…"
    return None


def _classify_line(line: str) -> tuple[_LineKind, str]:
    """Classify a pane line into a _LineKind event with payload.

    Returns (kind, payload) where payload is the extracted text for TEXT/CONTINUATION,
    or the tool identifier for TOOL_CALL.
    """
    s = line.strip()
    if not s:
        return _LineKind.SKIP, ""
    if _is_ui_chrome(s):
        return _LineKind.CHROME, ""
    if s == "❯":
        return _LineKind.DONE, ""
    if s.startswith(("⎿", "…")):
        return _LineKind.TOOL_OUTPUT, ""
    if s.startswith("⏺"):
        after = s[2:].strip()
        after = _strip_processing_suffix(after)
        if _TOOL_CALL_RE.match(after):
            return _LineKind.TOOL_CALL, after
        return _LineKind.TEXT, after
    if _SOURCES_HEADING_RE.match(s):
        return _LineKind.SOURCES_HEADING, ""
    # Continuation: not a special prefix → indented content
    if not s.startswith(("⏺", "⎿", "…", "❯")):
        return _LineKind.CONTINUATION, s
    return _LineKind.SKIP, ""


# ── High-level extraction ───────────────────────────────────────────────────


def _run_fsm(lines: list[str]) -> tuple[str, str | None]:
    """Run the FSM parser on a list of lines.

    Returns (accumulated_text, last_tool_progress).
    Shared by both _parse_delta_lines and _extract_response.
    """
    text_parts: list[str] = []
    last_tool_progress: str | None = None
    phase = _ParsePhase.IDLE

    for line in lines:
        kind, payload = _classify_line(line)

        # SOURCES is absorbing terminal — swallow everything
        if phase == _ParsePhase.SOURCES:
            continue
        # CHROME and SKIP are global filters
        if kind in (_LineKind.CHROME, _LineKind.SKIP):
            continue

        key = (phase, kind)
        next_phase, action = _TRANSITIONS.get(key, (phase, ""))
        phase = next_phase

        if action == "emit" and payload:
            text_parts.append(payload)
            last_tool_progress = None
        elif action == "progress":
            for pattern, label in _TOOL_LABEL_MAP:
                if pattern.match(payload):
                    last_tool_progress = label
                    break
            else:
                last_tool_progress = "處理中…"

    return "\n".join(text_parts).strip(), last_tool_progress


def _extract_response(before: str, after: str) -> str:
    """從 pane 內容擷取 Claude 最後的文字回應（timeout fallback 用）。"""
    lines = after.strip().splitlines()

    # 找最後一個有文字的 ❯ 行（使用者輸入行）
    prompt_idx = -1
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("❯") and len(s) > 2:
            prompt_idx = i

    if prompt_idx == -1:
        return ""

    # 找結尾 ❯
    end_idx = len(lines)
    for i in range(prompt_idx + 1, len(lines)):
        s = lines[i].strip()
        if s == "❯" or (s.startswith("❯") and s != lines[prompt_idx].strip()):
            end_idx = i
            break

    response_lines = lines[prompt_idx + 1 : end_idx]
    text, _ = _run_fsm(response_lines)
    return text


# ── Delta 擷取輔助 ──


def _extract_visible_lines_after_prompt(
    pane_content: str, prompt_idx_hint: int | None = None
) -> tuple[list[str], int]:
    """從 pane 內容中擷取提示行後的所有可見行。"""
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

    使用 FSM 追蹤 parsing phase，確保 Sources 區塊被吞掉、
    工具呼叫不洩漏、processing indicator 被剝除。
    """
    return _run_fsm(lines)


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
    _ensure_log_tail()
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

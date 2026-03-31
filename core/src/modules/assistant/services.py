"""Assistant service — Claude Code tmux persistent session.

Uses a dedicated tmux window with Claude Code (haiku) that has full
tool access: memvault recall, file reading, API calls, etc.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
import threading
from collections.abc import AsyncGenerator, Generator
from enum import StrEnum
from pathlib import Path

from src.shared.sse import BlockType, StreamBlock
from tmux_lib.cli_session import is_shell
from tmux_lib.primitives import display, send_enter, send_text, tmux_check, tmux_ok

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
_CHAT_LOG = "/tmp/assistant-chat.log"

_active_sessions: set[str] = set()


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


# ── JSONL Session Discovery ────────────────────────────────────────────────

_CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
_session_cache: dict[int, Path] = {}

# Tool name → friendly progress label (exact match, used by JSONL path)
_TOOL_NAME_LABEL: dict[str, str] = {
    "Bash": "執行指令中…",
    "Read": "讀取檔案中…",
    "Write": "寫入檔案中…",
    "Edit": "修改檔案中…",
    "Grep": "搜尋內容中…",
    "Glob": "搜尋檔案中…",
    "Skill": "呼叫技能中…",
    "Agent": "呼叫 Agent 中…",
    "Task": "執行任務中…",
    "WebSearch": "搜尋中…",
    "WebFetch": "擷取網頁中…",
    "ToolSearch": "搜尋工具中…",
}


def _resolve_session_jsonl() -> Path | None:
    """Discover JSONL file for the assistant tmux pane.

    Chain: pane_pid → child_pid → sessions/{pid}.json → sessionId → JSONL.
    """
    try:
        pane_pid_str = display(TMUX_TARGET, "#{pane_pid}")
        if not pane_pid_str:
            return None
        pane_pid = int(pane_pid_str.strip())

        result = subprocess.run(
            ["pgrep", "-P", str(pane_pid)],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        child_pid = int(result.stdout.strip().splitlines()[0])

        # Check cache
        if child_pid in _session_cache:
            cached = _session_cache[child_pid]
            if cached.exists():
                return cached

        session_file = _CLAUDE_SESSIONS_DIR / f"{child_pid}.json"
        if not session_file.exists():
            return None
        session_data = json.loads(session_file.read_text())
        session_id = session_data.get("sessionId")
        if not session_id:
            return None

        # Scan all project dirs for the JSONL (cwd varies)
        for jsonl in _CLAUDE_PROJECTS_DIR.glob(f"*/{session_id}.jsonl"):
            _session_cache[child_pid] = jsonl
            return jsonl

        return None
    except Exception:
        logger.debug("assistant: JSONL session discovery failed", exc_info=True)
        return None


def _extract_text_from_content(content: list[dict]) -> tuple[str, str | None]:
    """Extract (text, tool_progress) from assistant message content blocks."""
    texts: list[str] = []
    last_tool: str | None = None
    for block in content:
        btype = block.get("type")
        if btype == "text":
            t = block.get("text", "")
            if t:
                texts.append(t)
        elif btype == "tool_use":
            name = block.get("name", "")
            if name in _TOOL_NAME_LABEL:
                last_tool = _TOOL_NAME_LABEL[name]
            elif name.startswith("mcp__"):
                last_tool = "呼叫外部工具中…"
            else:
                last_tool = "處理中…"
    return "\n".join(texts), last_tool


def _iter_chat_jsonl(
    prompt: str, *, jsonl_path: Path, session_id: str = "",
) -> Generator[_DeltaEvent, None, None]:
    """JSONL file watcher: tail the session JSONL for assistant responses.

    Uses JSONL for text extraction (reliable, structured) and lightweight
    capture-pane only for activity detection (thinking/busy indicators).
    """
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

    # Record JSONL EOF before sending prompt
    try:
        baseline_offset = jsonl_path.stat().st_size
    except OSError:
        baseline_offset = 0

    # Send prompt (reuse existing tmux send logic)
    tmux_ok("send-keys", "-t", TMUX_TARGET, "-R")
    tmux_ok("clear-history", "-t", TMUX_TARGET)
    time.sleep(0.3)

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

    time.sleep(1.0)
    deadline = time.time() + _TIMEOUT
    sent_len = 0
    last_prog: str | None = None
    full_text = ""
    last_offset = baseline_offset
    _SPINNER_RE = re.compile(r"[⏺✢✻✽✦✧✳⠂]")

    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)

        # Read new JSONL lines
        new_entries = []
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                f.seek(last_offset)
                for raw in f:
                    raw = raw.strip()
                    if raw:
                        try:
                            new_entries.append(json.loads(raw))
                        except json.JSONDecodeError:
                            pass
                last_offset = f.tell()
        except OSError:
            pass

        # Process new entries
        done = False
        for entry in new_entries:
            etype = entry.get("type")
            if etype != "assistant":
                continue
            msg = entry.get("message", {})
            content = msg.get("content", [])
            text_part, tool_prog = _extract_text_from_content(content)

            if text_part:
                # Strip Sources section
                text_part = _strip_cc_noise(text_part)
                full_text += ("\n" if full_text else "") + text_part

            if tool_prog and tool_prog != last_prog:
                last_prog = tool_prog
                yield _DeltaEvent(tool_progress=tool_prog)

            stop = msg.get("stop_reason")
            if stop == "end_turn":
                done = True

        # Emit text delta
        if len(full_text) > sent_len:
            yield _DeltaEvent(text_delta=full_text[sent_len:])
            sent_len = len(full_text)

        if done:
            elapsed = time.time() - t0
            _log_chat(session_id=session_id, response=full_text, duration_s=elapsed)
            try:
                import redis as _redis
                _redis.Redis(decode_responses=True).set(
                    _REDIS_LAST_USED_KEY, str(int(time.time()))
                )
            except Exception:
                pass
            logger.info("assistant: done (jsonl), %d chars, %.1fs", sent_len, elapsed)
            yield _DeltaEvent(is_done=True)
            return

        # If no new JSONL data, check TUI for activity indicators
        if not new_entries:
            try:
                bottom = capture(TMUX_TARGET, start_line=-8, join_wrapped=True) or ""
                if _SPINNER_RE.search(bottom) and not last_prog:
                    yield _DeltaEvent(tool_progress="思考中…")
                    last_prog = "思考中…"
            except Exception:
                pass

    # Timeout fallback
    elapsed = time.time() - t0
    if full_text and len(full_text) > sent_len:
        yield _DeltaEvent(text_delta=full_text[sent_len:])
        _log_chat(session_id=session_id, response=full_text, duration_s=elapsed)
    yield _DeltaEvent(is_done=True)


def _ensure_assistant_window() -> bool:
    """Ensure tmux assistant window exists with Claude Code running."""
    with _startup_lock:
        return _ensure_assistant_window_inner()


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


_CC_NOISE_RE = re.compile(
    r"(?:\n|^)\s*[✢✻✳✶].*$"  # CC processing indicators (Concocting, Crunching, etc.)
    r"|(?:\n)\s*(?:Sources?|References?|Learn more)\s*:.*",
    re.DOTALL | re.MULTILINE,
)


def _strip_cc_noise(text: str) -> str:
    """Remove CC processing indicators and trailing Sources sections."""
    # Strip processing indicators line-by-line first
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        s = line.strip()
        if s and s[0] in "✢✻✳✶":
            continue  # CC processing indicator
        cleaned.append(line)
    text = "\n".join(cleaned)
    # Strip Sources section
    for marker in ("\nSources:", "\nSource:", "\nReferences:", "\nLearn more:"):
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx]
    return text.rstrip()


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
    if any(c in s for c in ("🔖", "🔧", "📁", "⎇", "🤖", "🐱", "🐢", "💰", "✍️", "⏵")):
        return True
    if "bypass" in s.lower() and "permission" in s.lower():
        return True
    if "shift+tab" in s.lower() or "tab to cycle" in s.lower():
        return True
    if s.count("─") > 10:
        return True
    # 處理中指示符（✢ ✻ ✳ ✶ + 獨立 · 行）
    if s.startswith(("✢", "✻", "✳", "✶", "✽", "✦", "✧", "·")):
        return True
    # Box border lines from tool call UI
    if s.startswith(("╭", "╰")) and "─" in s:
        return True
    if "Claude Code" in s or s.startswith("▐") or s.startswith("▝") or s.startswith("▘"):
        return True
    return False


def _is_tool_block(line: str) -> bool:
    """判斷 ⏺/● 行是否為工具呼叫（非文字內容）。"""
    s = line.strip()
    if not s.startswith(("⏺", "●")):
        return False
    after = s[1:].strip()
    return bool(_TOOL_CALL_RE.match(after))


def _strip_processing_suffix(text: str) -> str:
    """Remove CC processing indicator suffix (e.g. '· Architecting...')."""
    return _PROCESSING_SUFFIX_RE.sub("", text)


def _extract_tool_progress(line: str) -> str | None:
    """從工具呼叫行擷取進度描述。回傳人類可讀的簡短說明，或 None。"""
    s = line.strip()
    if not s.startswith(("⏺", "●")):
        return None
    after = s[1:].strip()
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
    if s.startswith(("⏺", "●")):
        # Both ⏺ (U+23FA) and ● (U+25CF) are single chars
        after = s[1:].strip()
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
    """Dispatch to JSONL-based or tmux FSM-based chat iteration."""
    jsonl_path = _resolve_session_jsonl()
    if jsonl_path is not None:
        logger.info("assistant: using JSONL path %s", jsonl_path.name)
        yield from _iter_chat_jsonl(prompt, jsonl_path=jsonl_path, session_id=session_id)
    else:
        logger.info("assistant: JSONL not found, using tmux FSM fallback")
        yield from _iter_chat_tmux(prompt, session_id=session_id)


def _iter_chat_tmux(prompt: str, *, session_id: str = "") -> Generator[_DeltaEvent, None, None]:
    """Tmux TUI fallback: send prompt to persistent CC, poll + FSM parse.

    Done detection waits for ❯ then drains until text stabilizes.
    """
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

    # Reset pane to avoid stale ❯ from previous Q&A
    tmux_ok("send-keys", "-t", TMUX_TARGET, "-R")
    tmux_ok("clear-history", "-t", TMUX_TARGET)
    time.sleep(0.3)
    before = capture(TMUX_TARGET, start_line=-200, join_wrapped=True) or ""

    # Send prompt with retry
    user_q = prompt[-20:]
    visible = False
    for attempt in range(1, 4):
        send_text(TMUX_TARGET, prompt, buf_name="_assistant_paste")
        time.sleep(0.15)
        send_enter(TMUX_TARGET)
        dl = time.time() + 5
        while time.time() < dl:
            time.sleep(0.3)
            cur = capture(TMUX_TARGET, start_line=-200, join_wrapped=True) or ""
            if user_q in cur and cur != before:
                visible = True
                break
        if visible:
            break
        time.sleep(1.0)
    if not visible:
        yield _DeltaEvent(text_delta="助手沒有回應，請再試一次", is_done=True)
        return

    time.sleep(1.0)
    deadline = time.time() + _TIMEOUT
    sent_len = 0
    last_prog: str | None = None

    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)
        try:
            cur = capture(TMUX_TARGET, start_line=-200, join_wrapped=True) or ""
        except Exception:
            break

        lines_after, pidx = _extract_visible_lines_after_prompt(cur)
        if pidx == -1:
            continue

        try:
            text, prog = _parse_delta_lines(lines_after)
        except Exception:
            continue
        text = _strip_cc_noise(text)

        # Detect done (❯ reappeared in tail)
        done = False
        if text:
            for line in lines_after[-5:] if len(lines_after) > 5 else lines_after:
                if line.strip() == "❯":
                    done = True
                    break

        # Emit delta
        if len(text) > sent_len:
            yield _DeltaEvent(text_delta=text[sent_len:])
            sent_len = len(text)

        if prog and prog != last_prog:
            last_prog = prog
            yield _DeltaEvent(tool_progress=prog)

        if done:
            # Drain: poll until text stabilizes (CC TUI render catch-up)
            for _ in range(10):
                time.sleep(0.3)
                try:
                    d = capture(TMUX_TARGET, start_line=-200, join_wrapped=True) or ""
                    dl2, _ = _extract_visible_lines_after_prompt(d)
                    if dl2:
                        dt, _ = _parse_delta_lines(dl2)
                        dt = _strip_cc_noise(dt)
                        if len(dt) > sent_len:
                            yield _DeltaEvent(text_delta=dt[sent_len:])
                            sent_len = len(dt)
                            text = dt
                        else:
                            break
                except Exception:
                    break

            elapsed = time.time() - t0
            _log_chat(session_id=session_id, response=text, duration_s=elapsed)
            try:
                import redis as _redis

                _redis.Redis(decode_responses=True).set(_REDIS_LAST_USED_KEY, str(int(time.time())))
            except Exception:
                pass
            logger.info("assistant: done, %d chars, %.1fs", sent_len, elapsed)
            yield _DeltaEvent(is_done=True)
            return

    # Timeout fallback
    elapsed = time.time() - t0
    try:
        cur = capture(TMUX_TARGET, start_line=-200, join_wrapped=True) or ""
        fb = _extract_response(before, cur)
        fb = _strip_cc_noise(fb)
    except Exception:
        fb = ""
    if fb and len(fb) > sent_len:
        yield _DeltaEvent(text_delta=fb[sent_len:])
        _log_chat(session_id=session_id, response=fb, duration_s=elapsed)
    yield _DeltaEvent(is_done=True)


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

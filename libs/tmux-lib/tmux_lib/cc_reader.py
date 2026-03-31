"""cc_reader.py — Shared Claude Code response reader for tmux panes.

Combines two orthogonal mechanisms:
  1. JSONL extraction  — structured, reliable text from ~/.claude/projects/
  2. Content stability — TUI-agnostic done detection (3 identical captures)

Primary consumers:
  - core/src/modules/assistant/services.py
  - stations/capture-console/server.py

Design:
  - JSONL text extraction is PRIMARY (structured, reliable)
  - Content-stability is used for DONE detection (TUI-agnostic)
  - If JSONL unavailable, fall back to TUI FSM parsing of stable pane content
  - Done = whichever comes first: JSONL end_turn OR stability (≥3 identical)
  - Spinner detection: check bottom 8 lines for ⏺✢✻✽✦✧✳⠂ during idle polls
  - min_wait: do not start stability checking until N seconds after prompt sent

Dependencies: tmux_lib.primitives + stdlib only (NO core/ or stations/ imports).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import time
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from tmux_lib.primitives import capture, capture_async, display

logger = logging.getLogger(__name__)

# ── Public types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CCDelta:
    """A single streaming delta from Claude Code."""

    text: str = ""
    tool_label: str | None = None
    is_done: bool = False


# ── Tool name → friendly progress label ─────────────────────────────────────

TOOL_NAME_LABEL: dict[str, str] = {
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

# ── JSONL session discovery constants ────────────────────────────────────────

_CLAUDE_SESSIONS_DIR = Path.home() / ".claude" / "sessions"
_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Module-level PID → Path cache (avoids repeated filesystem scans)
_session_cache: dict[int, Path] = {}


# ── Regex patterns ────────────────────────────────────────────────────────────

# Matches URL-only lines (Sources section entries)
_URL_LINE_RE = re.compile(
    r"^\s*[-•*]?\s*\[.*?\]\(https?://\S+\)\s*$"  # - [title](url)
    r"|^\s*[-•*]?\s*\*{0,2}.*?\*{0,2}\s*[：:]\s*https?://\S+\s*$"  # **label**: url
    r"|^\s*[-•*]?\s*https?://\S+\s*$",  # bare URL line
)

_SOURCES_HEADING_INLINE_RE = re.compile(
    r"^\s*\*{0,2}(?:Sources?|References?|Learn more)\s*[：:]\s*\*{0,2}\s*$",
    re.IGNORECASE,
)

# FSM-internal regexes
_TOOL_CALL_RE = re.compile(r"^(?:[A-Za-z_][\w. ]*\(|Task(?:\s|$|·))")

_PROCESSING_SUFFIX_RE = re.compile(
    r"\s+·\s+(?:Thinking|Architecting|Processing|Osmosing|Crunching|"
    r"Deciphering|Reticulating|Bunning|Iterating|Reflecting|Analyzing).*$",
    re.IGNORECASE,
)

_SOURCES_HEADING_RE = re.compile(r"^\s*(?:Sources?|References?|Learn more)\s*:\s*$", re.IGNORECASE)

# Spinner characters (used for activity detection)
_SPINNER_RE = re.compile(r"[⏺✢✻✽✦✧✳⠂]")

# Regex-based label map (covers TUI tool call lines)
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


# ── JSONL session discovery ───────────────────────────────────────────────────


def resolve_session_jsonl(pane: str) -> Path | None:
    """Discover JSONL file for a tmux pane via PID chain.

    Chain: pane_pid → child_pid → sessions/{child_pid}.json → sessionId → JSONL.

    Args:
        pane: tmux target pane (e.g. "assistant", "mywindow:1.0")

    Returns:
        Path to the JSONL file, or None if not found.
    """
    try:
        pane_pid_str = display(pane, "#{pane_pid}")
        if not pane_pid_str:
            return None
        pane_pid = int(pane_pid_str.strip())

        result = subprocess.run(
            ["pgrep", "-P", str(pane_pid)],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        child_pid = int(result.stdout.strip().splitlines()[0])

        # Check cache (validate to detect PID reuse)
        if child_pid in _session_cache:
            cached = _session_cache[child_pid]
            session_file_check = _CLAUDE_SESSIONS_DIR / f"{child_pid}.json"
            if cached.exists() and session_file_check.exists():
                try:
                    sid = json.loads(session_file_check.read_text()).get("sessionId", "")
                    if sid and sid in cached.name:
                        return cached
                except Exception:
                    pass
            del _session_cache[child_pid]  # Invalidate stale cache

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
        logger.debug("cc_reader: JSONL session discovery failed for pane=%s", pane, exc_info=True)
        return None


# ── JSONL content extraction ──────────────────────────────────────────────────


def extract_text_from_jsonl_entry(entry: dict) -> tuple[str, str | None]:
    """Extract (text, tool_progress) from a JSONL assistant message entry.

    Args:
        entry: A parsed JSONL line dict (type == "assistant")

    Returns:
        (text, tool_progress) where tool_progress is a human-readable label
        or None if no tool use was found.
    """
    msg = entry.get("message", {})
    content = msg.get("content", [])
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
            if name in TOOL_NAME_LABEL:
                last_tool = TOOL_NAME_LABEL[name]
            elif name.startswith("mcp__"):
                last_tool = "呼叫外部工具中…"
            else:
                last_tool = "處理中…"

    return "\n".join(texts), last_tool


# ── Noise filtering ───────────────────────────────────────────────────────────


def strip_cc_noise(text: str) -> str:
    """Remove CC noise: processing indicators, Sources sections, URL-only lines.

    Args:
        text: Raw text potentially containing CC TUI noise

    Returns:
        Cleaned text with noise removed.
    """
    lines = text.splitlines()
    cleaned: list[str] = []
    in_sources = False
    for line in lines:
        s = line.strip()
        # CC processing indicators
        if s and s[0] in "✢✻✳✶":
            continue
        # Sources/References heading → drop everything after
        if s and _SOURCES_HEADING_INLINE_RE.match(s):
            in_sources = True
            continue
        if in_sources:
            continue
        # Standalone URL lines (bare URLs, markdown link list items)
        if s and _URL_LINE_RE.match(line):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).rstrip()


# ── Content stability detection ───────────────────────────────────────────────


def wait_stable_sync(
    pane: str,
    *,
    baseline: str = "",
    interval: float = 0.3,
    required_stable: int = 3,
    timeout: float = 30.0,
) -> tuple[str, bool]:
    """Poll capture-pane until content stabilizes (synchronous).

    Content is considered stable when `required_stable` consecutive captures
    are identical AND different from `baseline`.

    Args:
        pane: tmux target pane
        baseline: content before the prompt was sent (to skip initial state)
        interval: seconds between polls
        required_stable: number of identical captures required
        timeout: maximum wait time in seconds

    Returns:
        (content, timed_out) — content is the stable capture, timed_out is True
        if we gave up before stability was reached.
    """
    start = time.time()
    prev = baseline
    stable = 0
    current = ""

    while time.time() - start < timeout:
        time.sleep(interval)
        current = capture(pane) or ""

        if current == baseline:
            continue  # nothing changed yet

        if current == prev:
            stable += 1
            if stable >= required_stable:
                logger.debug(
                    "cc_reader: stable after %.1fs (%d identical)",
                    time.time() - start,
                    stable,
                )
                return current, False
        else:
            stable = 0
            prev = current

    return current, True


async def wait_stable(
    pane: str,
    *,
    baseline: str = "",
    interval: float = 0.3,
    required_stable: int = 3,
    timeout: float = 30.0,
) -> tuple[str, bool]:
    """Poll capture-pane until content stabilizes (async version).

    Same semantics as wait_stable_sync but uses asyncio.sleep.

    Args:
        pane: tmux target pane
        baseline: content before the prompt was sent
        interval: seconds between polls
        required_stable: number of identical captures required
        timeout: maximum wait time in seconds

    Returns:
        (content, timed_out)
    """
    start = time.time()
    prev = baseline
    stable = 0
    current = ""

    while time.time() - start < timeout:
        await asyncio.sleep(interval)
        current = await capture_async(pane) or ""

        if current == baseline:
            continue  # nothing changed yet

        if current == prev:
            stable += 1
            if stable >= required_stable:
                logger.debug(
                    "cc_reader: stable after %.1fs (%d identical)",
                    time.time() - start,
                    stable,
                )
                return current, False
        else:
            stable = 0
            prev = current

    return current, True


# ── FSM parser (internal fallback) ───────────────────────────────────────────
#
# Used when JSONL is unavailable. Parses tmux capture-pane output using a
# finite state machine to extract clean text from CC's TUI output.
#
# States: IDLE → CONTENT / TOOL → SOURCES (absorbing terminal)
# Events: each line is classified into a _LineKind, transition table drives behavior.


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
    # SOURCES — absorbing: swallow everything (no entries needed, handled in loop)
}


def _is_ui_chrome(line: str) -> bool:
    """Return True if line is CC UI chrome (not user-visible content).

    Bug fixes applied:
      - ✢ included in processing indicators
      - 🔧🐱🐢 emoji pairs caught by emoji set check
      - ⏺/● followed by non-tool text → falls through (not chrome)
      - ╭╰ box borders from tool call UI
    """
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
    # Processing indicators: ✢ ✻ ✳ ✶ ✽ ✦ ✧ · (standalone)
    if s.startswith(("✢", "✻", "✳", "✶", "✽", "✦", "✧", "·")):
        return True
    # Box border lines from tool call UI (╭─... or ╰─...)
    if s.startswith(("╭", "╰")) and "─" in s:
        return True
    if "Claude Code" in s or s.startswith(("▐", "▝", "▘")):
        return True
    return False


def _is_tool_block(line: str) -> bool:
    """Return True if ⏺/● line is a tool call (not text content)."""
    s = line.strip()
    if not s.startswith(("⏺", "●")):
        return False
    after = s[1:].strip()
    return bool(_TOOL_CALL_RE.match(after))


def _strip_processing_suffix(text: str) -> str:
    """Remove CC processing indicator suffix (e.g. '· Architecting...')."""
    return _PROCESSING_SUFFIX_RE.sub("", text)


def _classify_line(line: str) -> tuple[_LineKind, str]:
    """Classify a pane line into a _LineKind event with payload.

    Returns:
        (kind, payload) where payload is extracted text for TEXT/CONTINUATION
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


def _run_fsm(lines: list[str]) -> tuple[str, str | None]:
    """Run the FSM parser on a list of lines.

    Args:
        lines: Lines from tmux capture-pane output after the user prompt

    Returns:
        (accumulated_text, last_tool_progress)
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


def _extract_fsm_from_pane(pane_content: str) -> tuple[str, str | None]:
    """Parse full pane content via FSM, returning text after the last prompt.

    Finds the last ❯<text> prompt line and parses everything after it.

    Returns:
        (text, last_tool_progress)
    """
    lines = pane_content.strip().splitlines()

    # Find last ❯<text> line (user input)
    prompt_idx = -1
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("❯") and len(s) > 2:
            prompt_idx = i

    if prompt_idx == -1:
        return "", None

    response_lines = lines[prompt_idx + 1 :]
    text, prog = _run_fsm(response_lines)
    return strip_cc_noise(text), prog


# ── Hybrid iterators ──────────────────────────────────────────────────────────


def iter_cc_response(
    pane: str,
    *,
    jsonl_path: Path | None = None,
    baseline_offset: int = 0,
    timeout: float = 180.0,
    poll_interval: float = 0.3,
    stable_count: int = 3,
    min_wait: float = 1.0,
) -> Generator[CCDelta, None, None]:
    """Hybrid sync iterator: JSONL for text extraction, stability for done detection.

    Strategy:
      1. If jsonl_path provided: tail JSONL for text + tool progress.
         Done = end_turn in JSONL OR (content stable for stable_count polls
         AND min_wait has elapsed).
      2. If no jsonl_path: auto-discover via resolve_session_jsonl(pane).
      3. Final fallback: FSM parse of stable pane content.

    Spinner detection: if no new JSONL data and bottom 8 lines contain a spinner
    character, yield a "思考中…" tool_label delta.

    Args:
        pane: tmux target pane
        jsonl_path: pre-resolved JSONL path (pass None to auto-discover)
        baseline_offset: byte offset in JSONL before the prompt was sent
        timeout: maximum streaming time in seconds
        poll_interval: seconds between polls
        stable_count: identical captures required for done detection
        min_wait: minimum seconds before stability-based done can trigger

    Yields:
        CCDelta events (text, tool_label, or is_done=True)
    """
    if jsonl_path is None:
        jsonl_path = resolve_session_jsonl(pane)

    t0 = time.time()
    deadline = t0 + timeout

    if jsonl_path is not None:
        # ── JSONL path ─────────────────────────────────────────────────────
        last_offset = baseline_offset
        sent_len = 0
        last_prog: str | None = None
        full_text = ""
        prev_capture: str | None = None
        stable = 0

        while time.time() < deadline:
            time.sleep(poll_interval)

            # Read new JSONL lines (binary mode for reliable seek/tell)
            new_entries: list[dict] = []
            try:
                with open(jsonl_path, "rb") as f:
                    f.seek(last_offset)
                    for raw_bytes in f:
                        try:
                            raw = raw_bytes.decode("utf-8").strip()
                        except UnicodeDecodeError:
                            break
                        if not raw:
                            last_offset = f.tell()
                            continue
                        try:
                            new_entries.append(json.loads(raw))
                            last_offset = f.tell()
                        except json.JSONDecodeError:
                            break
            except OSError:
                pass

            done = False
            for entry in new_entries:
                if entry.get("type") != "assistant":
                    continue
                text_part, tool_prog = extract_text_from_jsonl_entry(entry)

                if text_part:
                    text_part = strip_cc_noise(text_part)
                    full_text += ("\n" if full_text else "") + text_part

                if tool_prog and tool_prog != last_prog:
                    last_prog = tool_prog
                    yield CCDelta(tool_label=tool_prog)

                if entry.get("message", {}).get("stop_reason") == "end_turn":
                    done = True

            # Emit text delta
            if len(full_text) > sent_len:
                yield CCDelta(text=full_text[sent_len:])
                sent_len = len(full_text)

            if done:
                logger.debug("cc_reader: done via JSONL end_turn (%.1fs)", time.time() - t0)
                yield CCDelta(is_done=True)
                return

            # Stability-based done detection (only after min_wait)
            elapsed = time.time() - t0
            if elapsed >= min_wait:
                try:
                    cur = capture(pane) or ""
                    if prev_capture is not None and cur == prev_capture:
                        stable += 1
                        if stable >= stable_count:
                            logger.debug("cc_reader: done via stability (%.1fs)", elapsed)
                            # Drain any remaining text
                            if len(full_text) > sent_len:
                                yield CCDelta(text=full_text[sent_len:])
                            yield CCDelta(is_done=True)
                            return
                    else:
                        stable = 0
                    prev_capture = cur
                except Exception:
                    pass

            # Spinner detection (idle poll, no new JSONL data)
            if not new_entries:
                try:
                    bottom = capture(pane) or ""
                    # Only check bottom 8 lines
                    bottom_lines = "\n".join(bottom.splitlines()[-8:])
                    if _SPINNER_RE.search(bottom_lines) and not last_prog:
                        yield CCDelta(tool_label="思考中…")
                        last_prog = "思考中…"
                except Exception:
                    pass

        # Timeout — emit any remaining text
        if len(full_text) > sent_len:
            yield CCDelta(text=full_text[sent_len:])
        yield CCDelta(is_done=True)

    else:
        # ── FSM fallback path ──────────────────────────────────────────────
        logger.debug("cc_reader: no JSONL, falling back to FSM stability parse")
        # Wait for min_wait before starting stability detection
        if min_wait > 0:
            time.sleep(min(min_wait, timeout))

        stable_content, timed_out = wait_stable_sync(
            pane,
            interval=poll_interval,
            required_stable=stable_count,
            timeout=max(0.0, deadline - time.time()),
        )

        if stable_content:
            text, _ = _extract_fsm_from_pane(stable_content)
            if text:
                yield CCDelta(text=text)

        yield CCDelta(is_done=True)


async def aiter_cc_response(
    pane: str,
    *,
    jsonl_path: Path | None = None,
    baseline_offset: int = 0,
    timeout: float = 30.0,
    poll_interval: float = 0.3,
    stable_count: int = 3,
    min_wait: float = 1.0,
) -> AsyncGenerator[CCDelta, None]:
    """Async version of iter_cc_response.

    Same semantics as iter_cc_response but uses asyncio.sleep and capture_async.

    Args:
        pane: tmux target pane
        jsonl_path: pre-resolved JSONL path (pass None to auto-discover)
        baseline_offset: byte offset in JSONL before the prompt was sent
        timeout: maximum streaming time in seconds
        poll_interval: seconds between polls
        stable_count: identical captures required for done detection
        min_wait: minimum seconds before stability-based done can trigger

    Yields:
        CCDelta events (text, tool_label, or is_done=True)
    """
    if jsonl_path is None:
        jsonl_path = resolve_session_jsonl(pane)

    t0 = time.time()
    deadline = t0 + timeout

    if jsonl_path is not None:
        # ── Async JSONL path ───────────────────────────────────────────────
        last_offset = baseline_offset
        sent_len = 0
        last_prog: str | None = None
        full_text = ""
        prev_capture: str | None = None
        stable = 0

        while time.time() < deadline:
            await asyncio.sleep(poll_interval)

            new_entries: list[dict] = []
            try:
                with open(jsonl_path, "rb") as f:
                    f.seek(last_offset)
                    for raw_bytes in f:
                        try:
                            raw = raw_bytes.decode("utf-8").strip()
                        except UnicodeDecodeError:
                            break
                        if not raw:
                            last_offset = f.tell()
                            continue
                        try:
                            new_entries.append(json.loads(raw))
                            last_offset = f.tell()
                        except json.JSONDecodeError:
                            break
            except OSError:
                pass

            done = False
            for entry in new_entries:
                if entry.get("type") != "assistant":
                    continue
                text_part, tool_prog = extract_text_from_jsonl_entry(entry)

                if text_part:
                    text_part = strip_cc_noise(text_part)
                    full_text += ("\n" if full_text else "") + text_part

                if tool_prog and tool_prog != last_prog:
                    last_prog = tool_prog
                    yield CCDelta(tool_label=tool_prog)

                if entry.get("message", {}).get("stop_reason") == "end_turn":
                    done = True

            if len(full_text) > sent_len:
                yield CCDelta(text=full_text[sent_len:])
                sent_len = len(full_text)

            if done:
                logger.debug("cc_reader: done via JSONL end_turn (%.1fs)", time.time() - t0)
                yield CCDelta(is_done=True)
                return

            elapsed = time.time() - t0
            if elapsed >= min_wait:
                try:
                    cur = await capture_async(pane) or ""
                    if prev_capture is not None and cur == prev_capture:
                        stable += 1
                        if stable >= stable_count:
                            logger.debug("cc_reader: done via stability (%.1fs)", elapsed)
                            if len(full_text) > sent_len:
                                yield CCDelta(text=full_text[sent_len:])
                            yield CCDelta(is_done=True)
                            return
                    else:
                        stable = 0
                    prev_capture = cur
                except Exception:
                    pass

            if not new_entries:
                try:
                    bottom = await capture_async(pane) or ""
                    bottom_lines = "\n".join(bottom.splitlines()[-8:])
                    if _SPINNER_RE.search(bottom_lines) and not last_prog:
                        yield CCDelta(tool_label="思考中…")
                        last_prog = "思考中…"
                except Exception:
                    pass

        if len(full_text) > sent_len:
            yield CCDelta(text=full_text[sent_len:])
        yield CCDelta(is_done=True)

    else:
        # ── Async FSM fallback path ────────────────────────────────────────
        logger.debug("cc_reader: no JSONL, falling back to async FSM stability parse")
        if min_wait > 0:
            await asyncio.sleep(min(min_wait, timeout))

        stable_content, timed_out = await wait_stable(
            pane,
            interval=poll_interval,
            required_stable=stable_count,
            timeout=max(0.0, deadline - time.time()),
        )

        if stable_content:
            text, _ = _extract_fsm_from_pane(stable_content)
            if text:
                yield CCDelta(text=text)

        yield CCDelta(is_done=True)


# ── Public re-exports ─────────────────────────────────────────────────────────

__all__ = [
    "TOOL_NAME_LABEL",
    "CCDelta",
    "aiter_cc_response",
    "extract_text_from_jsonl_entry",
    "iter_cc_response",
    "resolve_session_jsonl",
    "strip_cc_noise",
    "wait_stable",
    "wait_stable_sync",
]

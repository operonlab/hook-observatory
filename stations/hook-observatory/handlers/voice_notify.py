"""
Voice notification handler with async TTS queue.

Events:
  PreToolUse/AskUserQuestion → random "請示" phrase
  Stop → task summary from state file, or "視窗X面板Y任務完成了"

Queue guarantees:
  - Non-blocking enqueue (hook returns immediately)
  - Sequential playback (one sound at a time, queued)
  - Self-cleaning consumer (exits after 3s idle)

TTS fallback chain: Workshop TTS service → edge-tts CLI → macOS say
Disable: CLAUDE_VOICE=0
"""

from __future__ import annotations

import fcntl
import json
import os
import random
import re
import subprocess

from .base import ALLOW, HOME, HookResult

# --- Configuration (env-overridable) ---
TTS_URL = os.environ.get("CLAUDE_TTS_URL", "http://localhost:8841/api/tts/speak")
VOICE = os.environ.get("CLAUDE_VOICE_ID", "zh-CN-YunjianNeural")
RATE = os.environ.get("CLAUDE_VOICE_RATE", "+20%")
PLAYBACK_VOL = os.environ.get("CLAUDE_VOICE_VOLUME", "0.4")
PYTHON_BIN = os.path.join(HOME, ".local", "bin", "python3")

QUEUE_FILE = "/tmp/claude-tts-queue.jsonl"
PID_FILE = "/tmp/claude-tts-consumer.pid"

_ASK_PHRASES = [
    "少爺，維恩有問題想請示您",
    "少爺，這裡需要您做個決定",
    "少爺，請您過目這幾個選項",
    "少爺，維恩需要您的指示",
    "少爺，有個問題想請教您",
]

_NUM_CN = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]


# ---------------------------------------------------------------------------
# Main handler (dispatcher entry point)
# ---------------------------------------------------------------------------


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if os.environ.get("CLAUDE_VOICE") == "0":
        return ALLOW

    if event_type == "PreToolUse" and tool_name == "AskUserQuestion":
        _enqueue_tts(random.choice(_ASK_PHRASES))
    elif event_type == "Stop":
        _handle_stop()
    return ALLOW


def _handle_stop() -> None:
    """Stop: announce task summary, or fall back to tmux position."""
    summary = _get_task_summary()
    if summary:
        _enqueue_tts(f"少爺，{summary}的任務完成了")
        return

    # Fallback: tmux position (視窗X面板Y) or generic
    label = _get_label()
    msg = f"少爺，{label}任務完成了" if label else "少爺，任務完成了"
    _enqueue_tts(msg)


# ---------------------------------------------------------------------------
# Task summary from state file (written by Claude via rules/voice-state.md)
# ---------------------------------------------------------------------------

TASK_STATE_PREFIX = "/tmp/claude-task-"


def _get_task_summary() -> str:
    """Read task summary from state file. Claude maintains this file via CLAUDE.md instruction."""
    pane_id = os.environ.get("TMUX_PANE", "")
    if not pane_id:
        return ""

    pane_safe = pane_id.replace("%", "")
    state_file = f"{TASK_STATE_PREFIX}{pane_safe}.txt"

    if not os.path.isfile(state_file):
        return ""

    try:
        with open(state_file) as f:
            summary = f.read().strip()
        os.remove(state_file)  # one-shot: clean up after reading
        return summary[:50] if summary else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Label detection (tmux pane name > window name > cwd)
# ---------------------------------------------------------------------------


def _get_label() -> str:
    label = os.environ.get("CLAUDE_LABEL", "")
    if label:
        return label

    pane_id = os.environ.get("TMUX_PANE", "")
    if pane_id:
        label = _tmux_label(pane_id)
        if label:
            return label

    return os.path.basename(os.getcwd())


def _tmux_label(pane_id: str) -> str:

    def _q(fmt: str) -> str:
        try:
            r = subprocess.run(
                ["tmux", "display-message", "-t", pane_id, "-p", fmt],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    # Prefer meaningful window name
    win_name = _q("#W")
    shell_defaults = ("zsh", "bash", "fish", "sh", "python", "python3", "node", "")
    if win_name and win_name not in shell_defaults:
        return win_name

    # Pane title (skip generic ones)
    pane_title = _q("#{pane_title}")
    pane_title = re.sub(r"^[^\w]*", "", pane_title)
    skip = ("", "-zsh", "-bash", "Claude Code", "Gemini CLI", "Codex CLI")
    if pane_title and pane_title not in skip and "@" not in pane_title:
        return pane_title

    # Window N Pane N (Chinese numerals)
    win_idx = _q("#I")
    pane_idx = _q("#P")
    if win_idx:
        w = _NUM_CN[int(win_idx)] if win_idx.isdigit() and int(win_idx) <= 9 else win_idx
        p = _NUM_CN[int(pane_idx)] if pane_idx.isdigit() and int(pane_idx) <= 9 else pane_idx
        return f"視窗{w}面板{p}"

    return ""


# ---------------------------------------------------------------------------
# TTS Queue — file-based JSONL + flock + background consumer
# ---------------------------------------------------------------------------


def _enqueue_tts(msg: str) -> None:
    """Append to queue file (atomic via flock) and ensure consumer alive."""
    entry = json.dumps(
        {"text": msg, "voice": VOICE, "rate": RATE, "vol": PLAYBACK_VOL},
        ensure_ascii=False,
    )
    with open(QUEUE_FILE, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(entry + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)
    _ensure_consumer()


def _consumer_alive() -> bool:
    """Check if TTS consumer process is still running."""
    if not os.path.isfile(PID_FILE):
        return False
    try:
        pid = int(open(PID_FILE).read().strip())
        os.kill(pid, 0)  # signal 0 = existence check
        return True
    except (OSError, ValueError):
        return False


def _ensure_consumer() -> None:
    """Start background consumer if not already running."""
    if _consumer_alive():
        return

    # Consumer is a self-contained Python script
    script = _build_consumer_script()
    subprocess.Popen(
        [PYTHON_BIN, "-c", script],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _build_consumer_script() -> str:
    """Build self-contained consumer script with current config baked in."""
    return f"""\
import fcntl, json, os, shutil, subprocess, sys, time
from urllib.request import Request, urlopen

QUEUE = {QUEUE_FILE!r}
PID   = {PID_FILE!r}
URL   = {TTS_URL!r}

# Register PID
with open(PID, "w") as f:
    f.write(str(os.getpid()))


def play(e):
    text  = e["text"]
    voice = e.get("voice", "zh-CN-YunjianNeural")
    rate  = e.get("rate", "+20%")
    vol   = e.get("vol", "0.3")

    # 1) Workshop TTS service
    try:
        payload = json.dumps({{
            "text": text, "voice": voice, "rate": rate,
            "wait": True, "playback_volume": float(vol),
        }})
        req = Request(URL, data=payload.encode(),
                      headers={{"Content-Type": "application/json"}})
        resp = urlopen(req, timeout=30)
        if resp.status == 200 and "json" in (resp.headers.get("Content-Type") or ""):
            return
    except Exception:
        pass

    # 2) edge-tts → afplay
    if shutil.which("edge-tts"):
        tmp = "/tmp/claude-tts-play.mp3"
        subprocess.run(
            ["edge-tts", "--voice", voice, "--rate", rate,
             "--text", text, "--write-media", tmp],
            capture_output=True, timeout=15,
        )
        subprocess.run(["afplay", "-v", vol, tmp],
                       capture_output=True, timeout=30)
        return

    # 3) macOS say → afplay
    if shutil.which("say"):
        tmp = "/tmp/claude-tts-play.aiff"
        subprocess.run(
            ["say", "-v", "Meijia", "-r", "320", "-o", tmp, text],
            capture_output=True, timeout=15,
        )
        subprocess.run(["afplay", "-v", vol, tmp],
                       capture_output=True, timeout=30)


def drain():
    if not os.path.isfile(QUEUE):
        return []
    with open(QUEUE, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        lines = f.readlines()
        f.seek(0)
        f.truncate()
        fcntl.flock(f, fcntl.LOCK_UN)
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln.strip()))
        except Exception:
            pass
    return out


# Main loop — drain queue, play sequentially, exit after 3s idle
idle = 0.0
while idle < 3.0:
    entries = drain()
    if not entries:
        time.sleep(0.5)
        idle += 0.5
        continue
    idle = 0.0
    for e in entries:
        try:
            play(e)
        except Exception:
            pass

# Cleanup
try:
    os.remove(PID)
except Exception:
    pass
"""

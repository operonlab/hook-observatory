"""
Voice notification handler — PreToolUse (AskUserQuestion) + Stop events.

Two modes:
  PreToolUse/AskUserQuestion → random "請示" phrase, non-blocking TTS
  Stop → background: parse transcript, LLM summarization, TTS playback

TTS fallback chain: Workshop TTS service → edge-tts CLI → macOS say

Set CLAUDE_VOICE=0 to disable.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
from urllib.request import Request, urlopen

from .base import ALLOW, HOME, HookResult, find_executable, run_background

# --- Configuration (env-overridable) ---
TTS_URL = os.environ.get("CLAUDE_TTS_URL", "http://localhost:8841/api/tts/speak")
VOICE = os.environ.get("CLAUDE_VOICE_ID", "zh-CN-YunjianNeural")
RATE = os.environ.get("CLAUDE_VOICE_RATE", "+20%")
PLAYBACK_VOL = os.environ.get("CLAUDE_VOICE_VOLUME", "0.3")
NOTIFY_LEVEL = os.environ.get("CLAUDE_NOTIFY_LEVEL", "action")
PYTHON_BIN = os.path.join(HOME, ".local", "bin", "python3")

_SEVERITY_RANK = {"urgent": 4, "action": 3, "warning": 2, "info": 1}

_ASK_PHRASES = [
    "少爺，維恩有問題想請示您",
    "少爺，這裡需要您做個決定",
    "少爺，請您過目這幾個選項",
    "少爺，維恩需要您的指示",
    "少爺，有個問題想請教您",
]

_NUM_CN = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if os.environ.get("CLAUDE_VOICE") == "0":
        return ALLOW

    if event_type == "PreToolUse" and tool_name == "AskUserQuestion":
        return _handle_ask()
    elif event_type == "Stop":
        return _handle_stop(raw_input)
    return ALLOW


def _handle_ask() -> HookResult:
    """AskUserQuestion: non-blocking TTS with random phrase."""
    msg = random.choice(_ASK_PHRASES)
    _tts_fire_and_forget(msg, severity="urgent", wait=False)
    return ALLOW


def _handle_stop(raw_input: str) -> HookResult:
    """Stop: background transcript parsing + LLM summary + TTS."""
    # Parse hook input for transcript path
    try:
        data = json.loads(raw_input) if raw_input.strip() else {}
    except (json.JSONDecodeError, AttributeError):
        data = {}

    transcript_path = data.get("transcript_path", "")
    label = _get_label()

    # All heavy work runs in background — hook returns immediately
    _spawn_stop_background(transcript_path, label)
    return ALLOW


# ---------------------------------------------------------------------------
# Label detection (identifies this pane/session)
# ---------------------------------------------------------------------------

def _get_label() -> str:
    """Get a meaningful label for this session (tmux pane name > cwd)."""
    # 1) Env var
    label = os.environ.get("CLAUDE_LABEL", "")
    if label:
        return label

    # 2) tmux identification
    pane_id = os.environ.get("TMUX_PANE", "")
    if pane_id:
        label = _tmux_label(pane_id)
        if label:
            return label

    # 3) Fallback: cwd basename
    return os.path.basename(os.getcwd())


def _tmux_label(pane_id: str) -> str:
    """Extract label from tmux window/pane names."""
    def _tmux_query(fmt: str) -> str:
        try:
            r = subprocess.run(
                ["tmux", "display-message", "-t", pane_id, "-p", fmt],
                capture_output=True, text=True, timeout=2,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    # Window name (skip shell defaults)
    win_name = _tmux_query("#W")
    if win_name and win_name not in ("zsh", "bash", "fish", "sh", "python", "python3", "node", ""):
        return win_name

    # Pane title (strip leading non-alnum)
    import re
    pane_title = _tmux_query("#{pane_title}")
    pane_title = re.sub(r"^[^\w]*", "", pane_title)
    skip = ("", "-zsh", "-bash", "Claude Code", "Gemini CLI", "Codex CLI")
    if pane_title and pane_title not in skip and "@" not in pane_title:
        return pane_title

    # Window N Pane N (Chinese numerals)
    win_idx = _tmux_query("#I")
    pane_idx = _tmux_query("#P")
    if win_idx:
        w = _NUM_CN[int(win_idx)] if win_idx.isdigit() and int(win_idx) <= 9 else win_idx
        p = _NUM_CN[int(pane_idx)] if pane_idx.isdigit() and int(pane_idx) <= 9 else pane_idx
        return f"視窗{w}面板{p}"

    return ""


# ---------------------------------------------------------------------------
# Background Stop processing
# ---------------------------------------------------------------------------

def _spawn_stop_background(transcript_path: str, label: str) -> None:
    """Spawn background process for Stop event heavy work."""
    # Build a self-contained Python script to run in background
    script = f'''
import json, os, subprocess, sys, time
from urllib.request import Request, urlopen

HOME = {HOME!r}
TTS_URL = {TTS_URL!r}
VOICE = {VOICE!r}
RATE = {RATE!r}
PLAYBACK_VOL = {PLAYBACK_VOL!r}
PYTHON_BIN = {PYTHON_BIN!r}
transcript_path = {transcript_path!r}
label = {label!r}

DBG = "/tmp/voice-notify-debug.log"
with open(DBG, "a") as f:
    f.write(f"=== {{time.strftime('%H:%M:%S')}} Stop ===\\n")

# Extract last user message from transcript
last_user_msg = ""
if transcript_path and os.path.isfile(transcript_path):
    try:
        with open(transcript_path) as f:
            first = f.read(1)
            f.seek(0)
            if first == "{{":
                data = json.load(f)
                for msg in data.get("messages", []):
                    if msg.get("type") != "user":
                        continue
                    content = msg.get("content", "")
                    text = ""
                    if isinstance(content, str):
                        text = content.strip()
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("text"):
                                text = c["text"].strip()
                                break
                            elif isinstance(c, str):
                                text = c.strip()
                                break
                    if text and not text.startswith("<system"):
                        last_user_msg = text
            else:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if obj.get("type") != "user":
                        continue
                    msg = obj.get("message", {{}})
                    content = msg.get("content", "") if isinstance(msg, dict) else obj.get("content", "")
                    text = ""
                    if isinstance(content, str):
                        text = content.strip()
                    elif isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get("text"):
                                text = c["text"].strip()
                                break
                            elif isinstance(c, str):
                                text = c.strip()
                                break
                    if text and not text.startswith("<system"):
                        last_user_msg = text
    except Exception:
        pass
if last_user_msg:
    last_user_msg = last_user_msg[:80]

# LLM summarization (codex → gemini fallback)
task_desc = ""
summary_prompt = f"用繁體中文10字內摘要這個需求，只輸出摘要不要其他文字：「{{last_user_msg}}」"
codex_cooldown = "/tmp/voice-notify-codex-cooldown"
cooldown_mins = 30

if last_user_msg:
    import shutil
    use_codex = True
    if os.path.isfile(codex_cooldown):
        age = time.time() - os.path.getmtime(codex_cooldown)
        if age < cooldown_mins * 60:
            use_codex = False
        else:
            os.remove(codex_cooldown)

    if use_codex and shutil.which("codex"):
        try:
            r = subprocess.run(
                ["codex", "exec", "--skip-git-repo-check", summary_prompt],
                capture_output=True, text=True, timeout=30,
            )
            task_desc = r.stdout.strip().split("\\n")[-1] if r.stdout.strip() else ""
            if not task_desc:
                open(codex_cooldown, "w").close()
        except Exception:
            open(codex_cooldown, "w").close()

    if not task_desc and shutil.which("gemini"):
        try:
            r = subprocess.run(
                ["gemini", "-p", summary_prompt, "-m", "gemini-2.5-flash"],
                capture_output=True, text=True, timeout=30,
            )
            task_desc = r.stdout.strip().split("\\n")[-1] if r.stdout.strip() else ""
        except Exception:
            pass

with open(DBG, "a") as f:
    f.write(f"LAST_USER_MSG=[{{last_user_msg}}]\\n")
    f.write(f"TASK_DESC=[{{task_desc}}]\\n")

# Build message
if task_desc:
    bg_msg = f"少爺，{{task_desc}}已完成"
elif label:
    bg_msg = f"少爺，{{label}}已完成"
else:
    bg_msg = "少爺，任務完成了"

with open(DBG, "a") as f:
    f.write(f"BG_MSG=[{{bg_msg}}]\\n")

# TTS playback
payload = json.dumps({{"text": bg_msg, "voice": VOICE, "rate": RATE, "wait": True, "playback_volume": float(PLAYBACK_VOL)}})
tts_ok = False
try:
    req = Request(TTS_URL, data=payload.encode(), headers={{"Content-Type": "application/json"}})
    resp = urlopen(req, timeout=30)
    if resp.status == 200 and "json" in (resp.headers.get("Content-Type") or ""):
        tts_ok = True
except Exception:
    pass

if not tts_ok:
    subprocess.run(["killall", "afplay"], capture_output=True)
    edge_tts = shutil.which("edge-tts")
    if edge_tts:
        tmp = "/tmp/claude-voice-notify-bg.mp3"
        subprocess.run([edge_tts, "--voice", VOICE, "--rate", RATE, "--text", bg_msg, "--write-media", tmp],
                       capture_output=True, timeout=15)
        subprocess.run(["afplay", "-v", PLAYBACK_VOL, tmp], capture_output=True, timeout=30)
    elif shutil.which("say"):
        tmp = "/tmp/claude-voice-notify-bg.aiff"
        subprocess.run(["say", "-v", "Meijia", "-r", "320", "-o", tmp, bg_msg], capture_output=True, timeout=15)
        subprocess.run(["afplay", "-v", PLAYBACK_VOL, tmp], capture_output=True, timeout=30)
'''
    run_background(
        [PYTHON_BIN, "-c", script],
    )


# ---------------------------------------------------------------------------
# Foreground TTS (for PreToolUse quick phrases)
# ---------------------------------------------------------------------------

def _tts_fire_and_forget(msg: str, severity: str = "action", wait: bool = True) -> None:
    """Send TTS request. Falls back through the chain on failure."""
    min_rank = _SEVERITY_RANK.get(NOTIFY_LEVEL, 3)
    cur_rank = _SEVERITY_RANK.get(severity, 3)
    if cur_rank < min_rank:
        if severity == "warning":
            _macos_notify("Claude Code ⚠️", msg)
        return

    payload = json.dumps({
        "text": msg, "voice": VOICE, "rate": RATE,
        "wait": wait, "playback_volume": float(PLAYBACK_VOL),
    })

    max_time = 30 if wait else 5

    # Try Workshop TTS service
    try:
        req = Request(TTS_URL, data=payload.encode(),
                      headers={"Content-Type": "application/json"})
        resp = urlopen(req, timeout=max_time)
        if resp.status == 200 and "json" in (resp.headers.get("Content-Type") or ""):
            if severity == "urgent":
                _macos_notify("Claude Code", msg)
            return
    except Exception:
        pass

    # Fallback: edge-tts
    subprocess.run(["killall", "afplay"], capture_output=True)
    edge_tts = find_executable("edge-tts")
    if edge_tts:
        tmp = "/tmp/claude-voice-notify.mp3"
        run_background(
            f'"{edge_tts}" --voice "{VOICE}" --rate "{RATE}" --text "{msg}" '
            f'--write-media "{tmp}" 2>/dev/null && afplay -v {PLAYBACK_VOL} "{tmp}" 2>/dev/null'
        )
        if severity == "urgent":
            _macos_notify("Claude Code", msg)
        return

    # Fallback: macOS say
    if find_executable("say"):
        run_background(
            f'say -v Meijia -r 320 -o /tmp/claude-voice-notify.aiff "{msg}" '
            f'&& afplay -v {PLAYBACK_VOL} /tmp/claude-voice-notify.aiff'
        )


def _macos_notify(title: str, msg: str) -> None:
    run_background(["osascript", "-e",
                    f'display notification "{msg}" with title "{title}"'])

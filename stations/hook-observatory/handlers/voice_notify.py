"""
=========================================================================
*** DEPRECATED — DO NOT EDIT ***  Source of truth has moved to Go.
=========================================================================
Authoritative implementation:
    ~/workshop/stations/hook-dispatcher/internal/handlers/voicenotify/

This Python module is retained ONLY as a panic-fallback for the Go
hook-dispatcher binary (via voice_notify_runner.py). It is never invoked
during normal operation. Edits made here will not affect TTS behaviour —
fix the Go port and `make install` instead.
=========================================================================

Voice notification handler with async TTS queue.

Events:
  PreToolUse/AskUserQuestion → random "請示" phrase + cancel pending TTS
  SubagentStart → track active sub-agent (Redis INCR) + cancel pending TTS
  SubagentStop → track completion (Redis DECR) + subtle sound effect
  Stop → deferred task announcement with activity-aware guards

Queue guarantees:
  - Non-blocking enqueue (hook returns immediately)
  - Sequential playback (one sound at a time, queued)
  - Self-cleaning consumer (exits after 3s idle)

Debounce:
  - Redis TTL-based: same pane won't announce twice within DEBOUNCE_TTL seconds
  - Key: tts:debounce:{pane_id}:{event_type}
  - Configurable via CLAUDE_VOICE_DEBOUNCE (default 10s, 0=disable)

TTS fallback chain: Workshop TTS service → edge-tts CLI → macOS say
Disable: CLAUDE_VOICE=0

Seven-guard state machine (prevents false "task done" announcements):
  Guard 0:   hook_event_name — skip non-Claude Stop events
  Guard 0.5: agent_type — skip Agent Teams teammate Stops
  Guard 1:   stop_hook_active — skip if hook is re-entrant
  Guard 1.5: active_agents > 0 — sub-agents still running (Redis counter)
  Guard 1.7: recent activity — sub-agent completed within settle window
  Guard 2:   last_assistant_message content analysis — detect intermediate states
  Guard 3:   Event separation — SubagentStop plays sound effect, Stop plays TTS
"""

from __future__ import annotations

import fcntl
import json
import os
import random
import re
import subprocess
import time

from .base import ALLOW, HOME, HookResult

# --- Intermediate-state detection patterns ---
# If the assistant's last message ends with these, it's NOT done yet.
_INTERMEDIATE_PATTERNS = [
    # Chinese patterns
    r"接下來",
    r"下一步",
    r"繼續\s*(處理|執行|進行)",
    r"我(會|將|來|先)",
    r"(那麼|好的|首先|然後)，?\s*(我|讓)",
    r"先(處理|檢查|看看|確認|完成)",
    r"(開始|著手)(處理|進行|執行)",
    r"讓我(再|繼續|先|來)",
    # English patterns
    r"let me continue",
    r"I'll now\b",
    r"I will now\b",
    r"next,?\s*I",
    r"moving on to",
    r"let me (?:check|read|look|fix|update|run|create|implement|start|explore|analyze)",
    r"now (?:let me|I'll|I will)",
    r"(?:first|then),?\s*(?:let me|I'll|I need to)",
    r"starting (?:with|by|to)",
    r"I need to (?:first|also|still)",
    # Question patterns (Stop before AskUserQuestion)
    r"\?\s*$",
    r"您(覺得|認為|希望|想要|選擇|確認)",
    r"請(選擇|確認|決定|告訴我)",
]
_INTERMEDIATE_RE = re.compile("|".join(_INTERMEDIATE_PATTERNS), re.IGNORECASE)

# Known sub-agent / teammate types that should NEVER trigger TTS on Stop
_TEAMMATE_TYPES = frozenset(
    {
        # Agent Teams built-in roles
        "Plan",
        "Explore",
        "Code",
        "Debug",
        "Review",
        # Custom sub-agent types (from ~/.claude/agents/)
        "worker",
        "explorer",
        "reviewer",
        "designer",
        "foreman",
        "researcher",
        "browser",
        "media",
        "codex-dispatcher",
        "gemini-dispatcher",
        "copilot-dispatcher",
        "writer",
        "statusline-setup",
        "claude-code-guide",
        "audit-context-building:function-analyzer",
        "chaos-engineer",
        "general-purpose",
    }
)

# Sub-agent completion sound effect (macOS system sound)
# Opt-in: set CLAUDE_SUBAGENT_SOUND=1 to enable Pop.aiff on SubagentStop
_SUBAGENT_SOUND = "/System/Library/Sounds/Pop.aiff"
_SUBAGENT_SOUND_ENABLED = os.environ.get("CLAUDE_SUBAGENT_SOUND", "0") == "1"
_SUBAGENT_VOLUME = os.environ.get("CLAUDE_SUBAGENT_VOLUME", "0.3")

# --- Configuration (env-overridable) ---
TTS_URL = os.environ.get("CLAUDE_TTS_URL", "http://localhost:10201/api/tts/speak")
VOICE = os.environ.get("CLAUDE_VOICE_ID", "zh-CN-YunjianNeural")
RATE = os.environ.get("CLAUDE_VOICE_RATE", "+20%")
PLAYBACK_VOL = os.environ.get("CLAUDE_VOICE_VOLUME", "0.4")
PYTHON_BIN = os.path.join(HOME, ".local", "bin", "python3")

QUEUE_FILE = "/tmp/claude-tts-queue.jsonl"
PID_FILE = "/tmp/claude-tts-consumer.pid"
DEBOUNCE_TTL = int(os.environ.get("CLAUDE_VOICE_DEBOUNCE", "10"))  # seconds, 0=disable
WEBUI_URL = os.environ.get("TMUX_WEBUI_URL", "http://127.0.0.1:10105")

# Activity tracking — deferred announcement settings
SETTLE_WINDOW = int(os.environ.get("CLAUDE_VOICE_SETTLE", "8"))  # seconds
_ACTIVE_TTL = 300  # safety net: orphaned counters expire after 5 min
_CHECKER_INTERVAL = 2  # background checker poll interval (seconds)
_CHECKER_MAX_WAIT = 45  # upper bound before force-announcing (seconds)

_ASK_PHRASES = [
    "少爺，維恩有問題想請示您",
    "少爺，這裡需要您做個決定",
    "少爺，請您過目這幾個選項",
    "少爺，維恩需要您的指示",
    "少爺，有個問題想請教您",
]

_NUM_CN = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]


# ---------------------------------------------------------------------------
# Redis debounce — same pane won't announce twice within TTL
# ---------------------------------------------------------------------------

_redis_client = None


def _get_redis():
    """Lazy-init Redis client (fail-open: returns None on error)."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis

        _redis_client = redis.Redis(host="127.0.0.1", port=6379, socket_timeout=2.0)
        _redis_client.ping()
        return _redis_client
    except Exception:
        _redis_client = False  # sentinel: don't retry
        return None


def _debounce_ok(event_type: str, session_id: str = "") -> bool:
    """Two-layer debounce: per-event + shared completion cooldown.

    Layer 1 (per-event): same event type won't fire twice within TTL.
    Layer 2 (completion cooldown): Stop/SubagentStop share a cooldown,
        so a SubagentStop at T=0 suppresses a Stop at T=2.

    Identity resolution: TMUX_PANE > session_id (from hook JSON) > ppid.
    """
    if DEBOUNCE_TTL <= 0:
        return True

    # Stable identity: prefer TMUX_PANE, fallback to session_id from hook JSON
    ident = os.environ.get("TMUX_PANE", "")
    if not ident:
        ident = session_id or f"pid-{os.getppid()}"

    r = _get_redis()
    if not r:
        return True  # fail-open: Redis down → allow

    try:
        # Layer 1: per-event debounce (same event type won't double-fire)
        key = f"tts:debounce:{ident}:{event_type}"
        if not bool(r.set(key, 1, nx=True, ex=DEBOUNCE_TTL)):
            return False

        # Layer 2: shared completion cooldown (Stop + SubagentStop mutually exclusive)
        if event_type in ("stop", "subagent_stop"):
            cooldown_key = f"tts:cooldown:{ident}"
            if not bool(r.set(cooldown_key, 1, nx=True, ex=DEBOUNCE_TTL)):
                return False
    except Exception:
        return True  # fail-open

    return True


# ---------------------------------------------------------------------------
# Session activity tracking — Redis-based sub-agent lifecycle awareness
# ---------------------------------------------------------------------------


def _get_ident(session_id: str = "") -> str:
    """Stable identity for Redis keys: TMUX_PANE > session_id > ppid."""
    ident = os.environ.get("TMUX_PANE", "")
    if not ident:
        ident = session_id or f"pid-{os.getppid()}"
    return ident


def _track_subagent_start(ident: str) -> None:
    """Increment active sub-agent counter and cancel any pending TTS."""
    r = _get_redis()
    if not r:
        return
    try:
        pipe = r.pipeline()
        pipe.incr(f"tts:active_agents:{ident}")
        pipe.expire(f"tts:active_agents:{ident}", _ACTIVE_TTL)
        pipe.set(f"tts:last_activity:{ident}", str(time.time()), ex=_ACTIVE_TTL)
        pipe.delete(f"tts:pending:{ident}")  # cancel deferred TTS
        pipe.execute()
    except Exception:
        pass  # fail-open


def _track_subagent_stop(ident: str) -> None:
    """Decrement active sub-agent counter and update last activity timestamp."""
    r = _get_redis()
    if not r:
        return
    try:
        pipe = r.pipeline()
        pipe.decr(f"tts:active_agents:{ident}")
        pipe.expire(f"tts:active_agents:{ident}", _ACTIVE_TTL)
        pipe.set(f"tts:last_activity:{ident}", str(time.time()), ex=_ACTIVE_TTL)
        pipe.execute()
        # Floor at 0 — prevent negative counter from missed SubagentStart
        val = r.get(f"tts:active_agents:{ident}")
        if val is not None and int(val) < 0:
            r.set(f"tts:active_agents:{ident}", 0, ex=_ACTIVE_TTL)
    except Exception:
        pass


def _has_active_subagents(ident: str) -> bool:
    """Check if there are still active sub-agents for this identity."""
    r = _get_redis()
    if not r:
        return False  # fail-open: no Redis → assume no active sub-agents
    try:
        val = r.get(f"tts:active_agents:{ident}")
        return val is not None and int(val) > 0
    except Exception:
        return False


def _recent_subagent_activity(ident: str) -> bool:
    """Check if a sub-agent completed within the settle window."""
    r = _get_redis()
    if not r:
        return False
    try:
        ts_str = r.get(f"tts:last_activity:{ident}")
        if ts_str is None:
            return False
        return (time.time() - float(ts_str)) < SETTLE_WINDOW
    except Exception:
        return False


def _cancel_pending_tts(ident: str) -> None:
    """Cancel any deferred TTS announcement for this identity."""
    r = _get_redis()
    if not r:
        return
    try:
        r.delete(f"tts:pending:{ident}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main handler (dispatcher entry point)
# ---------------------------------------------------------------------------


def handle(event_type: str, tool_name: str, tool_input: dict, raw_input: str) -> HookResult:
    if os.environ.get("CLAUDE_VOICE") == "0":
        return ALLOW

    if event_type == "PreToolUse" and tool_name == "AskUserQuestion":
        # About to ask a question → cancel any pending "task done" announcement
        ident = _get_ident()
        _cancel_pending_tts(ident)
        if _debounce_ok("ask"):
            _enqueue_tts(random.choice(_ASK_PHRASES))

    elif event_type == "SubagentStart":
        # Track: new sub-agent starting → increment counter + cancel pending TTS
        data = _parse_event_data(raw_input)
        ident = _get_ident(data.get("session_id", ""))
        _track_subagent_start(ident)

    elif event_type == "SubagentStop":
        # Track: sub-agent finished → decrement counter + update activity
        data = _parse_event_data(raw_input)
        session_id = data.get("session_id", "")
        ident = _get_ident(session_id)
        _track_subagent_stop(ident)
        # Guard 3: sub-agent completion → subtle sound effect, not TTS
        if _debounce_ok("subagent_stop", session_id):
            _play_sound_effect()

    elif event_type == "Stop":
        data = _parse_event_data(raw_input)
        session_id = data.get("session_id", "")
        ident = _get_ident(session_id)

        # Guard 0: skip non-Claude events (e.g. Gemini CLI AfterAgent mapped to Stop)
        hook_name = data.get("hook_event_name", "")
        if hook_name and hook_name != "Stop":
            return ALLOW

        # Guard 0.5: skip teammate/sub-agent Stops (Agent Teams in-process mode)
        agent_type = data.get("agent_type", data.get("subagent_type", ""))
        if agent_type and agent_type in _TEAMMATE_TYPES:
            return ALLOW

        # Guard 1: skip if stop hook is re-entrant (prevents infinite loops)
        if data.get("stop_hook_active"):
            return ALLOW

        # Guard 2: check last_assistant_message for intermediate signals
        last_msg = data.get("last_assistant_message", "")
        if _is_intermediate(last_msg):
            return ALLOW

        # Guards 1.5 + 1.7 are inside _handle_stop_with_tracking
        if _debounce_ok("stop", session_id):
            _handle_stop_with_tracking(ident)

    return ALLOW


def _parse_event_data(raw_input: str) -> dict:
    """Parse raw JSON input from hook event. Fail-open: returns {} on error."""
    try:
        if raw_input and raw_input.strip():
            return json.loads(raw_input)
    except (json.JSONDecodeError, AttributeError):
        pass
    return {}


def _is_intermediate(msg: str) -> bool:
    """Detect if the last assistant message indicates work-in-progress, not completion.

    Checks the tail of the message for patterns like "接下來", "let me continue",
    "I'll now", etc. that signal the agent is still mid-task.
    """
    if not msg:
        return False
    # Only check the tail — completion signals appear at the end
    tail = msg[-300:]
    return bool(_INTERMEDIATE_RE.search(tail))


def _play_sound_effect() -> None:
    """Play a subtle macOS sound effect for sub-agent completion (non-blocking)."""
    if not _SUBAGENT_SOUND_ENABLED:
        return
    if os.path.isfile(_SUBAGENT_SOUND):
        subprocess.Popen(
            ["afplay", "-v", _SUBAGENT_VOLUME, _SUBAGENT_SOUND],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _build_stop_message() -> str:
    """Build the TTS message for task completion."""
    summary = _get_task_summary()
    if summary:
        return f"少爺，{summary}的任務完成了"
    label = _get_label()
    return f"少爺，{label}任務完成了" if label else "少爺，任務完成了"


def _handle_stop_with_tracking(ident: str) -> None:
    """Activity-aware Stop handler: defer TTS if sub-agents are active."""
    msg = _build_stop_message()
    r = _get_redis()

    if not r:
        # fail-open: Redis down → announce immediately (legacy behavior)
        _enqueue_tts(msg)
        return

    try:
        active = int(r.get(f"tts:active_agents:{ident}") or 0)
        last_act = float(r.get(f"tts:last_activity:{ident}") or 0)
        now = time.time()

        # Guard 1.5: sub-agents still running → defer
        # Guard 1.7: recent sub-agent activity within settle window → defer
        if active > 0 or (last_act > 0 and (now - last_act) < SETTLE_WINDOW):
            _defer_announcement(r, ident, msg)
            return
    except Exception:
        pass  # fail-open: fall through to immediate announce

    _enqueue_tts(msg)


def _defer_announcement(r, ident: str, msg: str) -> None:
    """Write pending TTS to Redis and spawn background checker."""
    try:
        pending = json.dumps({"msg": msg, "queued_at": time.time()})
        r.set(f"tts:pending:{ident}", pending, ex=_CHECKER_MAX_WAIT + 10)
    except Exception:
        # fail-open: can't defer → announce immediately
        _enqueue_tts(msg)
        return

    # Spawn lightweight checker process
    checker_pid = f"/tmp/tts-checker-{ident.replace('%', '')}.pid"
    if _process_alive(checker_pid):
        return  # checker already running — it will pick up new pending
    script = _build_checker_script(ident)
    subprocess.Popen(
        [PYTHON_BIN, "-c", script],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _process_alive(pid_file: str) -> bool:
    """Check if a process identified by pid_file is still running."""
    if not os.path.isfile(pid_file):
        return False
    try:
        pid = int(open(pid_file).read().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _build_checker_script(ident: str) -> str:
    """Build self-contained background checker that waits for activity to settle.

    The checker polls Redis every CHECK_INTERVAL seconds. When conditions are met
    (no active sub-agents, no recent activity), it writes to the TTS queue file
    and either delegates to the existing consumer or plays directly via edge-tts/say.
    """
    return f"""\
import fcntl, json, os, shutil, subprocess, sys, time

IDENT = {ident!r}
PID_FILE = "/tmp/tts-checker-{ident.replace("%", "")}.pid"
QUEUE_FILE = {QUEUE_FILE!r}
CONSUMER_PID = {PID_FILE!r}
CHECK_INTERVAL = {_CHECKER_INTERVAL}
MAX_WAIT = {_CHECKER_MAX_WAIT}
SETTLE = {SETTLE_WINDOW}
VOICE = {VOICE!r}
RATE = {RATE!r}
VOL = {PLAYBACK_VOL!r}

with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))

try:
    import redis
    r = redis.Redis(host="127.0.0.1", port=6379, socket_timeout=2.0)
    r.ping()
except Exception:
    try:
        os.remove(PID_FILE)
    except Exception:
        pass
    sys.exit(0)


def announce(msg):
    # Try 1: write to queue file (existing consumer may pick it up)
    entry = json.dumps({{"text": msg, "voice": VOICE, "rate": RATE, "vol": VOL}},
                       ensure_ascii=False)
    try:
        with open(QUEUE_FILE, "a") as fq:
            fcntl.flock(fq, fcntl.LOCK_EX)
            fq.write(entry + "\\n")
            fcntl.flock(fq, fcntl.LOCK_UN)
    except Exception:
        pass
    # Check if consumer is alive
    alive = False
    try:
        pid = int(open(CONSUMER_PID).read().strip())
        os.kill(pid, 0)
        alive = True
    except Exception:
        pass
    if alive:
        return  # consumer will handle playback
    # Try 2: direct synthesis + playback (no consumer available)
    tmp = "/tmp/claude-tts-deferred.mp3"
    if shutil.which("edge-tts"):
        subprocess.run(
            ["edge-tts", "--voice", VOICE, "--rate", RATE,
             "--text", msg, "--write-media", tmp],
            capture_output=True, timeout=15,
        )
        if os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
            subprocess.run(["afplay", "-v", VOL, tmp],
                           capture_output=True, timeout=30)
            return
    # Try 3: macOS say
    if shutil.which("say"):
        tmp2 = "/tmp/claude-tts-deferred.aiff"
        subprocess.run(
            ["say", "-v", "Meijia", "-r", "320", "-o", tmp2, msg],
            capture_output=True, timeout=15,
        )
        if os.path.isfile(tmp2) and os.path.getsize(tmp2) > 0:
            subprocess.run(["afplay", "-v", VOL, tmp2],
                           capture_output=True, timeout=30)


waited = 0.0
while waited < MAX_WAIT:
    time.sleep(CHECK_INTERVAL)
    waited += CHECK_INTERVAL

    pending_raw = r.get(f"tts:pending:{{IDENT}}")
    if not pending_raw:
        break  # cancelled

    try:
        active = int(r.get(f"tts:active_agents:{{IDENT}}") or 0)
    except Exception:
        active = 0
    if active > 0:
        continue

    try:
        last_act = float(r.get(f"tts:last_activity:{{IDENT}}") or 0)
    except Exception:
        last_act = 0
    if last_act > 0 and (time.time() - last_act) < SETTLE:
        continue

    # All clear — fire TTS
    try:
        pending = json.loads(pending_raw)
        msg = pending.get("msg", "")
        if msg:
            announce(msg)
    except Exception:
        pass
    r.delete(f"tts:pending:{{IDENT}}")
    break
else:
    # MAX_WAIT exceeded — force announce (fail-safe)
    pending_raw = r.get(f"tts:pending:{{IDENT}}")
    if pending_raw:
        try:
            pending = json.loads(pending_raw)
            msg = pending.get("msg", "")
            if msg:
                announce(msg)
        except Exception:
            pass
        r.delete(f"tts:pending:{{IDENT}}")

try:
    os.remove(PID_FILE)
except Exception:
    pass
"""


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
    """Append to queue file (atomic via flock) and ensure consumer alive.

    Fail-open: if the queue file cannot be written (e.g. /tmp full), we
    return silently rather than crashing the hook — TTS errors must never
    block Claude Code.
    """
    entry = json.dumps(
        {"text": msg, "voice": VOICE, "rate": RATE, "vol": PLAYBACK_VOL},
        ensure_ascii=False,
    )
    try:
        with open(QUEUE_FILE, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(entry + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        return  # fail-open: TTS failure must never block the hook
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
import base64, fcntl, json, os, shutil, subprocess, sys, time
from urllib.request import Request, urlopen

QUEUE = {QUEUE_FILE!r}
PID   = {PID_FILE!r}
URL   = {TTS_URL!r}
WEBUI = {WEBUI_URL!r}

# Register PID
with open(PID, "w") as f:
    f.write(str(os.getpid()))


def push_to_webui(path, text):
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        payload = json.dumps({{"audio": b64, "text": text}})
        req = Request(WEBUI + "/api/tts/push", data=payload.encode(),
                      headers={{"Content-Type": "application/json"}})
        urlopen(req, timeout=3)
    except Exception:
        pass


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
            push_to_webui("/tmp/claude-tts-play.mp3", text)
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
        push_to_webui(tmp, text)
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
        push_to_webui(tmp, text)


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

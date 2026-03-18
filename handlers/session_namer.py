"""
Session auto-namer + color — Stop & UserPromptSubmit handler.

On the first Stop event of a session, spawns a background process that:
1. Reads the session transcript to get the first user message
2. Calls Haiku to generate a 2-4 word kebab-case title + prompt bar color
3. Stores in ~/.claude/data/session-titles.json (external registry)

On UserPromptSubmit, if a color has been assigned but not yet applied,
injects a one-time hint so the model can suggest `/color <name>`.

Non-blocking: spawns background process, returns ALLOW immediately.
Fail-open: any error -> silently skip, never block Claude Code.

Avoids known pitfalls:
- 64KB truncation bug (#33165): uses external JSON registry, not session JSONL
- Resume name loss (#26240): external registry persists independently
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime

from .base import ALLOW, HOME, HookResult, text_result

logger = logging.getLogger(__name__)

REGISTRY_PATH = os.path.join(HOME, ".claude", "data", "session-titles.json")
VALID_COLORS = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"}


def _load_registry() -> dict:
    try:
        with open(REGISTRY_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def handle(
    event_type: str,
    tool_name: str,
    tool_input: dict,
    raw_input: str,
) -> HookResult:
    """Name the session on first Stop event (non-blocking)."""
    if os.environ.get("CLAUDE_SESSION_NAMER", "1") == "0":
        return ALLOW

    try:
        # Resolve session_id
        session_id = os.environ.get("CLAUDE_SESSION_ID", "")
        if not session_id:
            try:
                data = json.loads(raw_input) if raw_input else {}
                session_id = data.get("session_id", "")
            except Exception:  # noqa: S110
                pass

        if not session_id:
            return ALLOW

        # Already named? Skip.
        registry = _load_registry()
        if session_id in registry:
            return ALLOW

        # Spawn background namer process
        code = (
            "import os, sys, json, glob, fcntl\n"
            "from datetime import datetime, timezone\n"
            "\n"
            "HOME = os.path.expanduser('~')\n"
            "REGISTRY = os.path.join(HOME, '.claude', 'data', 'session-titles.json')\n"
            f"session_id = {session_id!r}\n"
            "\n"
            "# Find transcript\n"
            "pattern = os.path.join(HOME, '.claude', 'projects', '**', f'{session_id}.jsonl')\n"
            "matches = glob.glob(pattern, recursive=True)\n"
            "if not matches:\n"
            "    sys.exit(0)\n"
            "\n"
            "# Extract first user message\n"
            "first_message = ''\n"
            "try:\n"
            "    with open(matches[0]) as f:\n"
            "        for line in f:\n"
            "            line = line.strip()\n"
            "            if not line:\n"
            "                continue\n"
            "            entry = json.loads(line)\n"
            "            msg_obj = entry.get('message', {}) or {}\n"
            "            role = entry.get('type', '') or msg_obj.get('role', '')\n"
            "            if role == 'user':\n"
            "                msg = msg_obj\n"
            "                content = msg.get('content', '')\n"
            "                if isinstance(content, list):\n"
            "                    for block in content:\n"
            "                        if isinstance(block, dict) and block.get('type') == 'text':\n"
            "                            first_message = block.get('text', '')\n"
            "                            break\n"
            "                elif isinstance(content, str):\n"
            "                    first_message = content\n"
            "                if first_message:\n"
            "                    break\n"
            "except Exception:\n"
            "    sys.exit(0)\n"
            "\n"
            "if not first_message.strip():\n"
            "    sys.exit(0)\n"
            "\n"
            "# Call Haiku via claude CLI (inherits OAuth auth)\n"
            "import subprocess as _sp\n"
            "try:\n"
            "    prompt = ('Generate a session title and pick a prompt-bar color.\\n'\n"
            "              'Title: 2-4 word kebab-case, verb-first, max 30 chars.\\n'\n"
            "              'Color: pick ONE from [red,blue,green,yellow,purple,orange,pink,cyan] '\n"  # noqa: E501
            "              'that matches the task mood/domain.\\n'\n"
            '              \'Return ONLY JSON: {"title":"...","color":"..."}\\n\\n\'\n'
            "              f'User message: {first_message[:500]}')\n"
            "    r = _sp.run(\n"
            "        ['claude', '-p', prompt, '--model', 'haiku', '--output-format', 'text',\n"
            "         '--no-session-persistence'],\n"
            "        capture_output=True, text=True, timeout=120,\n"
            "        env={**os.environ, 'CTX_SUPERVISOR_LEVEL': 'off',\n"
            "             'CLAUDE_SESSION_NAMER': '0'},\n"
            "    )\n"
            "    raw = r.stdout.strip()\n"
            "    # Strip markdown code fences (```json ... ```)\n"
            "    import re as _re\n"
            "    m = _re.search(r'\\{[^}]*\"title\"[^}]*\\}', raw)\n"
            "    if m:\n"
            "        raw = m.group()\n"
            "    try:\n"
            "        parsed = json.loads(raw)\n"
            "        title = parsed.get('title', '').strip()\n"
            "        color = parsed.get('color', '').strip().lower()\n"
            "    except Exception:\n"
            "        title = raw.strip()\n"
            "        color = ''\n"
            "    valid = {'red','blue','green','yellow','purple','orange','pink','cyan'}\n"
            "    if color not in valid:\n"
            "        color = ''\n"
            "except Exception:\n"
            "    sys.exit(0)\n"
            "\n"
            "if not title:\n"
            "    sys.exit(0)\n"
            "\n"
            "# Write to registry with file lock\n"
            "os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)\n"
            "try:\n"
            "    with open(REGISTRY, 'a+') as f:\n"
            "        fcntl.flock(f, fcntl.LOCK_EX)\n"
            "        f.seek(0)\n"
            "        content = f.read().strip()\n"
            "        registry = json.loads(content) if content else {}\n"
            "        created = datetime.now(timezone.utc).isoformat()\n"
            "        registry[session_id] = {\n"
            "            'title': title, 'color': color, 'created_at': created}\n"
            "        f.seek(0)\n"
            "        f.truncate()\n"
            "        json.dump(registry, f, indent=2)\n"
            "        fcntl.flock(f, fcntl.LOCK_UN)\n"
            "except Exception:\n"
            "    pass\n"
        )

        subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:  # noqa: S110
        pass  # fail-open: never block Claude Code

    return ALLOW


def batch_rename_sessions(session_paths: list[str]) -> dict[str, dict]:
    """Batch-name up to 50 sessions using a single RLM call.

    Extracts the first and last user messages from each session transcript,
    sends them all as context to RLM, and gets back titles + colors.

    Falls back to individual naming on RLM failure.

    Args:
        session_paths: List of absolute paths to session JSONL files (max 50).

    Returns:
        Dict mapping session_id -> {"title": str, "color": str, "status": str}.
    """
    import re
    import sys as _sys

    _sys.path.insert(0, "/Users/joneshong/workshop/core")

    from src.shared.rlm_engine import RLMConfig, RLMEngine

    session_paths = session_paths[:50]
    results: dict[str, dict] = {}

    # Extract first + last user messages from each session
    session_contexts: list[dict] = []
    for path in session_paths:
        session_id = os.path.basename(path).replace(".jsonl", "")
        first_msg = ""
        last_msg = ""
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg_obj = entry.get("message", {}) or {}
                    role = entry.get("type", "") or msg_obj.get("role", "")
                    if role != "user":
                        continue
                    content = msg_obj.get("content", "")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = block.get("text", "")
                                break
                        else:
                            text = ""
                    elif isinstance(content, str):
                        text = content
                    else:
                        text = ""
                    if text.strip():
                        if not first_msg:
                            first_msg = text[:300]
                        last_msg = text[:300]
        except Exception:  # noqa: S110
            pass  # skip unreadable session files; continue to next path

        if first_msg:
            session_contexts.append(
                {
                    "session_id": session_id,
                    "first_message": first_msg,
                    "last_message": last_msg if last_msg != first_msg else "",
                }
            )

    if not session_contexts:
        return results

    # Build context for RLM
    context_str = json.dumps(session_contexts, ensure_ascii=False, indent=2)

    prompt = (
        f"為以下 {len(session_contexts)} 個 Claude Code session 生成標題和顏色。\n\n"
        "規則:\n"
        "- title: 2-4 word kebab-case, verb-first, max 30 chars\n"
        "- color: 從 [red,blue,green,yellow,purple,orange,pink,cyan] 選一個匹配任務氛圍\n\n"
        "以 JSON 回覆:\n"
        '{"sessions": [{"session_id": "...", "title": "...", "color": "..."}, ...]}\n\n'
        "FINAL() 包住你的 JSON。"
    )

    config = RLMConfig(
        model="haiku",
        sub_model="haiku",
        max_iterations=3,
        max_timeout_secs=45.0,
        max_depth=1,
    )
    engine = RLMEngine(config)

    try:
        rlm_result = engine.completion(prompt=prompt, context=context_str)

        if rlm_result.status != "ok":
            return results

        raw = rlm_result.response
        raw = re.sub(r"```(?:json)?\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return results

        data = json.loads(match.group())
        sessions_list = data.get("sessions", [])

        # Write all to registry at once
        os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
        try:
            with open(REGISTRY_PATH, "a+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.seek(0)
                content = f.read().strip()
                registry = json.loads(content) if content else {}

                for entry in sessions_list:
                    sid = entry.get("session_id", "")
                    title = entry.get("title", "").strip()
                    color = entry.get("color", "").strip().lower()
                    if not sid or not title:
                        continue
                    if color not in VALID_COLORS:
                        color = ""
                    registry[sid] = {
                        "title": title,
                        "color": color,
                        "created_at": datetime.now(UTC).isoformat(),
                    }
                    results[sid] = {"title": title, "color": color, "status": "ok"}

                f.seek(0)
                f.truncate()
                json.dump(registry, f, indent=2)
                fcntl.flock(f, fcntl.LOCK_UN)
        except Exception:
            logger.debug("session_namer: failed to write registry", exc_info=True)

    except Exception:
        logger.debug("session_namer: batch naming failed, returning partial results", exc_info=True)

    return results


def handle_color_hint(
    event_type: str,
    tool_name: str,
    tool_input: dict,
    raw_input: str,
) -> HookResult:
    """Inject one-time color hint on UserPromptSubmit."""
    if os.environ.get("CLAUDE_SESSION_NAMER", "1") == "0":
        return ALLOW

    try:
        session_id = os.environ.get("CLAUDE_SESSION_ID", "")
        if not session_id:
            return ALLOW

        # Fast check: already hinted this session?
        marker = f"/tmp/.claude-color-hinted-{session_id}"  # noqa: S108
        if os.path.exists(marker):
            return ALLOW

        registry = _load_registry()
        entry = registry.get(session_id, {})
        color = entry.get("color", "")

        if color and color in VALID_COLORS:
            # Create marker — hint only once per session
            with open(marker, "w") as f:
                f.write(color)
            return text_result(
                f"Session color assigned: {color} — suggest user run `/color {color}`"
            )
    except Exception:  # noqa: S110
        pass

    return ALLOW

"""Capture Console Station — Claude Code interactive tmux relay + WebSocket.

Architecture:
  - Persistent Claude Code session in tmux (default:3.1)
  - WebSocket relay: browser → WS → tmux send-keys → capture-pane → response
  - Conversation context preserved across messages (interactive session, not headless)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from tmux_lib.cli_session import is_process_running_async, start_cli_async
from tmux_lib.patterns import CLAUDE_CODE
from tmux_lib.primitives import (
    capture_async,
    send_enter_async,
    send_text_async,
    tmux_run_async,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("capture-console")

# Shared Redis key with capture_watchdog.py / llm_haiku.py
_REDIS_LAST_USED_KEY = "capture:haiku:last_used"
_WATCHDOG_TS_FILE = "/tmp/capture_watchdog_ts"


def _touch_last_used() -> None:
    """Update capture:haiku:last_used so capture_watchdog.py knows we're active."""
    now = str(int(time.time()))
    # File fallback (always works)
    try:
        with open(_WATCHDOG_TS_FILE, "w") as f:
            f.write(now)
    except OSError:
        pass
    # Redis (best-effort)
    try:
        import redis as _redis

        r = _redis.Redis(decode_responses=True)
        r.set(_REDIS_LAST_USED_KEY, now)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TMUX_SESSION = os.getenv("CAPTURE_TMUX_SESSION", "default")
CAPTURE_WINDOW = os.getenv("CAPTURE_WINDOW", "3")
CAPTURE_PANE = os.getenv("CAPTURE_PANE", "1")
HOST = os.getenv("CAPTURE_HOST", "127.0.0.1")
PORT = int(os.getenv("CAPTURE_PORT", "10104"))
CLAUDE_TIMEOUT = float(os.getenv("CAPTURE_CLAUDE_TIMEOUT", "30"))
CLAUDE_MODEL = os.getenv("CAPTURE_CLAUDE_MODEL", "haiku")

TMUX_TARGET = f"{TMUX_SESSION}:{CAPTURE_WINDOW}.{CAPTURE_PANE}"

SYSTEM_PROMPT = (
    "你是 Workshop 平台的捕捉解析助理。"
    "使用者會給你簡短的自然語言描述（如消費、任務、投資、日程），"
    "你必須將其解析成結構化 JSON。\n\n"
    "## 規則\n"
    "1. 禁止使用任何工具或 MCP server。只回覆純文字 JSON。\n"
    "2. 回覆格式必須是 ```json\\n{...}\\n``` code block。\n"
    "3. 用繁體中文回覆 notes 欄位。\n\n"
    "## JSON 結構\n"
    "```json\n"
    '{"module":"finance|taskflow|invest|dailyos|intelflow",'
    '"entity_type":"transaction|subscription|installment|task|trade|plan_item|webcrawl",'
    '"payload":{...},"confidence":0.0-1.0,"notes":"..."}\n'
    "```\n\n"
    "## Payload 欄位\n"
    "- finance/transaction: type(expense|income), amount, description, currency(TWD), "
    "payment_method(credit_card|cash|transfer), category_id, wallet_id, transacted_at\n"
    "- finance/subscription: name, amount, billing_cycle(monthly|yearly), start_date\n"
    "- finance/installment: description, total_amount, installment_count, merchant, start_date\n"
    "- taskflow/task: title, description, priority(low|medium|high|urgent), due_date, source, project\n"
    "- invest/trade: position_id, type(buy|sell), shares, price, traded_at, currency\n"
    "- dailyos/plan_item: title, priority(low|medium|high), plan_date, estimated_hours, category\n"
    "- intelflow/webcrawl: url, title, tags\n\n"
    "## 智慧預設\n"
    "未指定時：type=expense, currency=TWD, payment_method=credit_card, priority=medium\n"
    "transacted_at/plan_date 預設今天。\n\n"
    "## 解析範例\n"
    '- 「午餐 150」→ finance/transaction {amount:150, description:"午餐"}\n'
    '- 「Netflix 390/月」→ finance/subscription {name:"Netflix", amount:390, billing_cycle:"monthly"}\n'
    '- 「明天下午開會三小時」→ dailyos/plan_item {title:"開會", estimated_hours:3, plan_date:"明天"}\n'
    '- 「買 10 張台積電 850」→ invest/trade {shares:10, price:850, type:"buy"}'
)
# Idle cleanup delegated to capture_watchdog.py (Cronicle, 30-min threshold)

# Prompt file for Claude startup command (avoids shell escaping)
_PROMPT_FILE = "/tmp/capture-console-system-prompt.txt"

# JSON extraction patterns
_JSON_BLOCK_RE = re.compile(r"```json\s*([\s\S]*?)```")
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*?\"module\"[\s\S]*?\"payload\"[\s\S]*?\}")

# Claude Code TUI detection
_BORDER_RE = re.compile(r"^[─━]{20,}$")
_TUI_NOISE = re.compile(r"🔖|🤖|⏵⏵|bypass|Checking for update|shift\+tab|💰|✍️|📁|⎇")

# Serialization lock — one tmux interaction at a time
_query_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# tmux helpers (delegated to workshop.tmux.*)
# ---------------------------------------------------------------------------


async def pane_exists() -> bool:
    """Check if the target tmux pane exists."""
    r = await tmux_run_async("has-session", "-t", TMUX_SESSION)
    if not r.ok:
        return False
    r = await tmux_run_async(
        "list-panes",
        "-t",
        f"{TMUX_SESSION}:{CAPTURE_WINDOW}",
        "-F",
        "#{pane_index}",
    )
    if not r.ok:
        return False
    return CAPTURE_PANE in r.stdout.split("\n")


# ---------------------------------------------------------------------------
# Claude Code session management
# ---------------------------------------------------------------------------


async def _ensure_pane() -> bool:
    """Ensure the tmux window/pane exists. Create if missing."""
    # Check session
    r = await tmux_run_async("has-session", "-t", TMUX_SESSION)
    if not r.ok:
        log.error("tmux session '%s' does not exist", TMUX_SESSION)
        return False

    # Check if window exists
    r = await tmux_run_async(
        "list-windows",
        "-t",
        TMUX_SESSION,
        "-F",
        "#{window_index}",
    )
    windows = r.stdout.split("\n") if r.ok else []

    if CAPTURE_WINDOW not in windows:
        # Create the window (named "capture")
        log.info("Creating tmux window %s:%s (capture)", TMUX_SESSION, CAPTURE_WINDOW)
        r = await tmux_run_async(
            "new-window",
            "-t",
            f"{TMUX_SESSION}:{CAPTURE_WINDOW}",
            "-n",
            "capture",
        )
        if not r.ok:
            log.error("Failed to create window: %s", r.stderr)
            return False
        await asyncio.sleep(0.5)

    # Check if target pane exists within the window
    if not await pane_exists():
        # Window exists but pane index doesn't — split to create it
        log.info("Creating pane %s in window %s", CAPTURE_PANE, CAPTURE_WINDOW)
        r = await tmux_run_async(
            "split-window",
            "-t",
            f"{TMUX_SESSION}:{CAPTURE_WINDOW}",
        )
        if not r.ok:
            log.error("Failed to create pane: %s", r.stderr)
            return False
        await asyncio.sleep(0.3)

    return await pane_exists()


async def ensure_claude() -> bool:
    """Ensure Claude Code is running in the tmux pane. Create pane if needed."""
    if not await _ensure_pane():
        return False

    # Write system prompt to file (avoids shell escaping nightmares)
    with open(_PROMPT_FILE, "w") as f:
        f.write(SYSTEM_PROMPT)

    start_cmd = (
        f"claude --model {CLAUDE_MODEL} --dangerously-skip-permissions"
        f' --system-prompt "$(cat {_PROMPT_FILE})"'
    )
    started = await start_cli_async(
        TMUX_TARGET, start_cmd, CLAUDE_CODE, wait_timeout=10, poll_interval=0.5
    )
    if started:
        log.info("Claude Code ready in %s", TMUX_TARGET)
    else:
        log.error("Failed to start Claude Code in %s", TMUX_TARGET)
    return started


# ---------------------------------------------------------------------------
# Response extraction
# ---------------------------------------------------------------------------


def _extract_response(content: str) -> str:
    """Extract Claude's latest response from pane content.

    Claude Code TUI renders responses with ⏺ (record) prefix and ⎿ (continuation).
    JSON may appear raw (no ```json fences) in the TUI output.
    """
    # Strategy 1: ```json code block (if Claude wrapped it)
    blocks = _JSON_BLOCK_RE.findall(content)
    if blocks:
        return f"```json\n{blocks[-1].strip()}\n```"

    # Strategy 2: extract response lines from TUI (between last ❯ input and idle prompt)
    lines = content.split("\n")
    response_lines: list[str] = []
    last_input_idx = -1

    # Find the LAST user input line (❯ followed by text)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("❯") and stripped not in ("❯", "❯ "):
            last_input_idx = i

    if last_input_idx >= 0:
        # Collect everything after the input line until the idle prompt border
        for i in range(last_input_idx + 1, len(lines)):
            stripped = lines[i].strip()
            if _BORDER_RE.match(stripped):
                # Could be end-of-response or start of idle prompt
                # Check if next non-empty line is ❯ (idle prompt)
                for j in range(i + 1, min(i + 4, len(lines))):
                    if lines[j].strip() in ("❯", "❯ "):
                        break  # reached idle prompt, stop collecting
                else:
                    continue  # border within response, keep going
                break
            if _TUI_NOISE.search(stripped):
                continue
            # Clean TUI prefixes
            cleaned = re.sub(r"^\s*[⏺⎿]\s?", "", lines[i])
            response_lines.append(cleaned)

    text = "\n".join(response_lines).strip()

    # Try to parse as JSON and wrap in code fence for the frontend
    if text:
        try:
            obj = json.loads(text)
            if "module" in obj and "payload" in obj:
                return f"```json\n{json.dumps(obj, ensure_ascii=False, indent=2)}\n```"
        except (json.JSONDecodeError, TypeError):
            pass

    return text or "(空回應)"


# ---------------------------------------------------------------------------
# Query Claude via tmux relay
# ---------------------------------------------------------------------------


async def query_claude(message: str) -> str:
    """Send a message to Claude Code via tmux and capture the response."""
    async with _query_lock:
        if not await ensure_claude():
            raise RuntimeError("Claude Code 未執行且無法啟動")
        _touch_last_used()

        before = await capture_async(TMUX_TARGET) or ""

        # Send message via tmux (literal mode avoids key-name interpretation)
        safe_msg = message.replace("\n", " ")
        await send_text_async(TMUX_TARGET, safe_msg)
        await asyncio.sleep(0.1)
        await send_enter_async(TMUX_TARGET)

        # Content-stability approach:
        # Claude Code TUI animates during thinking (✻ Cogitating…) — content
        # keeps changing. Once response is complete, content stabilizes.
        # Wait for 3 consecutive identical captures (~0.9s of no change).
        start = time.time()
        prev = before
        stable = 0

        while time.time() - start < CLAUDE_TIMEOUT:
            await asyncio.sleep(0.3)
            current = await capture_async(TMUX_TARGET) or ""

            if current == before:
                continue  # nothing changed yet

            if current == prev:
                stable += 1
                if stable >= 3:
                    log.info("Response stable (%.1fs)", time.time() - start)
                    return _extract_response(current)
            else:
                stable = 0
                prev = current

        raise TimeoutError("Claude Code 回應逾時")


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


app = FastAPI(title="Capture Console", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    pane_ok = await pane_exists()
    claude_ok = await is_process_running_async(TMUX_TARGET, CLAUDE_CODE) if pane_ok else False
    return {
        "status": "ok" if claude_ok else ("degraded" if pane_ok else "down"),
        "pane": TMUX_TARGET,
        "claude_running": claude_ok,
        "model": CLAUDE_MODEL,
    }


@app.websocket("/ws")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    log.info("WebSocket connected")

    claude_ok = await ensure_claude()
    if not claude_ok:
        await ws.send_json(
            {
                "type": "error",
                "message": f"無法啟動 Claude Code（tmux pane {TMUX_TARGET} 不存在或啟動失敗）",
            }
        )
        await ws.close()
        return

    await ws.send_json(
        {
            "type": "status",
            "message": f"已連線 Claude Code 解析引擎 ({CLAUDE_MODEL})",
        }
    )

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if data.get("type") != "message":
                continue

            text = data.get("text", "").strip()
            if not text:
                continue

            msg_id = int(time.time() * 1000)

            # Build prompt with context
            context = data.get("context")
            prompt_parts: list[str] = []
            if context:
                prompt_parts.append(
                    f"[補充情境: {context.get('module')}/{context.get('entity_type')}, "
                    f"缺少欄位={context.get('missing_fields', [])}, "
                    f"目前 payload={json.dumps(context.get('payload', {}), ensure_ascii=False)}]"
                )
            prompt_parts.append(text)
            full_prompt = " ".join(prompt_parts)

            try:
                log.info("Querying Claude: %s", full_prompt[:100])
                response = await query_claude(full_prompt)

                await ws.send_json(
                    {
                        "type": "chunk",
                        "text": response.strip(),
                        "msg_id": msg_id,
                    }
                )
            except TimeoutError:
                await ws.send_json(
                    {
                        "type": "chunk",
                        "text": "Claude Code 回應逾時，請重試。",
                        "msg_id": msg_id,
                    }
                )
            except Exception as e:
                log.error("Claude query failed: %s", e)
                await ws.send_json(
                    {
                        "type": "chunk",
                        "text": f"查詢失敗：{e}",
                        "msg_id": msg_id,
                    }
                )

            await ws.send_json({"type": "done", "msg_id": msg_id})

    except WebSocketDisconnect:
        log.info("WebSocket disconnected")
    except Exception as e:
        log.error("WebSocket error: %s", e)
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")

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
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from tmux_lib.cc_reader import aiter_cc_response, resolve_session_jsonl
from tmux_lib.cli_session import is_process_running_async
from tmux_lib.patterns import CLAUDE_CODE
from tmux_lib.primitives import (
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
    # File fallback (always works, watchdog reads this too)
    try:
        with open(_WATCHDOG_TS_FILE, "w") as f:
            f.write(now)
    except OSError:
        pass
    # Redis (log on failure — silent failures caused 11-day stale timestamp)
    try:
        import redis as _redis

        r = _redis.Redis(decode_responses=True)
        r.set(_REDIS_LAST_USED_KEY, now)
    except Exception:
        log.warning("_touch_last_used: Redis write failed — watchdog relies on file fallback")


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
    "3. 用繁體中文回覆 notes 欄位。\n"
    "4. 嚴禁任何解釋性文字、歡迎訊息、後續建議。只輸出 JSON code block。\n"
    "5. 即使信心度低，仍以 JSON 格式回覆（在 notes 欄位說明原因）。\n"
    "6. CRITICAL: 回覆只能有一個 ```json code block，前後不可有任何文字。\n\n"
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
    """Ensure Claude Code is running AND idle in the tmux pane."""
    if not await _ensure_pane():
        return False

    # Write system prompt to file (avoids shell escaping nightmares)
    with open(_PROMPT_FILE, "w") as f:
        f.write(SYSTEM_PROMPT)

    from tmux_lib.cli_session import (
        is_shell_async,
        start_cli_async,
        wait_for_prompt_async,
    )

    if await is_shell_async(TMUX_TARGET):
        # CC not running — start it and wait for ❯ prompt
        start_cmd = (
            f"CLAUDE_VOICE=0 claude --model {CLAUDE_MODEL} --effort low"
            f" --dangerously-skip-permissions"
            f' --system-prompt "$(cat {_PROMPT_FILE})"'
        )
        started = await start_cli_async(
            TMUX_TARGET,
            start_cmd,
            CLAUDE_CODE,
            wait_timeout=25,
            poll_interval=0.5,
        )
        if not started:
            log.error("Failed to start Claude Code in %s", TMUX_TARGET)
            return False
        log.info("Claude Code started and ready in %s", TMUX_TARGET)
        _touch_last_used()
        return True

    # CC already running — just verify it's idle
    ready = await wait_for_prompt_async(
        TMUX_TARGET,
        CLAUDE_CODE,
        timeout=15,
        poll_interval=0.5,
    )
    if not ready:
        log.error("Claude Code running but not idle in %s", TMUX_TARGET)
    return ready


# ---------------------------------------------------------------------------
# Response post-processing
# ---------------------------------------------------------------------------


def _wrap_as_json_block(text: str) -> str:
    """Wrap structured JSON responses in a ```json code fence for the frontend.

    If the text already contains a json code block, return as-is.
    If it looks like a raw JSON object with 'module' and 'payload' keys,
    pretty-print and wrap it. Otherwise return the text unchanged.
    """
    stripped = text.strip()

    # Already wrapped in a code fence
    if "```json" in stripped:
        return stripped

    # Try to parse as raw JSON object
    try:
        obj = json.loads(stripped)
        if "module" in obj and "payload" in obj:
            return f"```json\n{json.dumps(obj, ensure_ascii=False, indent=2)}\n```"
    except (json.JSONDecodeError, TypeError):
        pass

    return stripped or "(空回應)"


# ---------------------------------------------------------------------------
# Query Claude via tmux relay
# ---------------------------------------------------------------------------


async def query_claude(message: str) -> str:
    """Send a message to Claude Code via tmux and capture the response."""
    async with _query_lock:
        # Ensure CC is running AND idle (handles watchdog /exit recovery)
        if not await ensure_claude():
            raise RuntimeError("Claude Code 未執行且無法啟動")
        _touch_last_used()

        # Discover JSONL path before sending (establishes baseline offset)
        jsonl_path = await asyncio.to_thread(resolve_session_jsonl, TMUX_TARGET)
        baseline_offset = 0
        if jsonl_path:
            try:
                baseline_offset = jsonl_path.stat().st_size
            except OSError:
                pass

        # Send raw message — system prompt handles JSON-only output
        safe_msg = message.replace("\n", " ")
        await send_text_async(TMUX_TARGET, safe_msg)
        await asyncio.sleep(0.1)
        await send_enter_async(TMUX_TARGET)

        # Use shared hybrid reader (JSONL primary + stability fallback)
        full_text = ""
        async for delta in aiter_cc_response(
            TMUX_TARGET,
            jsonl_path=jsonl_path,
            baseline_offset=baseline_offset,
            timeout=CLAUDE_TIMEOUT,
        ):
            if delta.text:
                full_text += delta.text
            if delta.is_done:
                break

        if not full_text:
            raise TimeoutError("Claude Code 回應逾時")

        log.info("Response received (%d chars)", len(full_text))

        # Capture-console specific: wrap JSON in code fence for the frontend
        return _wrap_as_json_block(full_text)


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

"""Capture Console Station — Gemini CLI headless enrichment + WebSocket relay.

Architecture:
  - WebSocket relay: browser → WS → gemini -p (headless) → parsed response
  - Each message spawns a headless Gemini CLI subprocess (no TUI parsing needed)
  - tmux pane (default:3.1) kept for manual Gemini interaction / health display
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("capture-console")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TMUX_SESSION = os.getenv("CAPTURE_TMUX_SESSION", "default")
GEMINI_WINDOW = os.getenv("CAPTURE_GEMINI_WINDOW", "3")
GEMINI_PANE = os.getenv("CAPTURE_GEMINI_PANE", "1")
HOST = os.getenv("CAPTURE_HOST", "127.0.0.1")
PORT = int(os.getenv("CAPTURE_PORT", "4104"))
GEMINI_TIMEOUT = float(os.getenv("CAPTURE_GEMINI_TIMEOUT", "30"))

GEMINI_TARGET = f"{TMUX_SESSION}:{GEMINI_WINDOW}.{GEMINI_PANE}"

SYSTEM_PROMPT = (
    "你是 Workshop 平台的捕捉解析助理。"
    "使用者會給你簡短的自然語言描述（如消費、任務、投資），"
    "你必須將其解析成結構化 JSON。\n\n"
    "## 規則\n"
    "1. 禁止使用任何工具或 MCP server。只回覆純文字 JSON。\n"
    "2. 回覆格式必須是 ```json\\n{...}\\n``` code block。\n"
    "3. 用繁體中文回覆 notes 欄位。\n\n"
    "## JSON 結構\n"
    "```json\n"
    '{"module":"finance|taskflow|invest",'
    '"entity_type":"transaction|subscription|installment|task|trade",'
    '"payload":{...},"confidence":0.0-1.0,"notes":"..."}\n'
    "```\n\n"
    "## Payload 欄位\n"
    "- finance/transaction: type(expense|income), amount, description, currency(TWD), "
    "payment_method(credit_card|cash|transfer), category_id, wallet_id, transacted_at\n"
    "- finance/subscription: name, amount, billing_cycle(monthly|yearly), start_date\n"
    "- taskflow/task: title, description, priority(low|medium|high|urgent), due_date, source, project\n"
    "- invest/trade: position_id, type(buy|sell), shares, price, traded_at, currency\n\n"
    "## 智慧預設\n"
    "未指定時：type=expense, currency=TWD, payment_method=credit_card, priority=medium\n"
    "transacted_at 預設今天。"
)

# Regex to extract JSON from markdown code block
_JSON_BLOCK_RE = re.compile(r"```json\s*([\s\S]*?)```")
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\"module\"[\s\S]*\"payload\"[\s\S]*\}")


# ---------------------------------------------------------------------------
# tmux helpers (for health check / manual pane)
# ---------------------------------------------------------------------------


async def _run(args: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        return -1, "", "timeout"
    return proc.returncode or 0, (stdout or b"").decode(), (stderr or b"").decode()


async def gemini_pane_alive() -> bool:
    """Check if the Gemini pane exists in tmux."""
    rc, out, _ = await _run(
        [
            "tmux",
            "list-panes",
            "-t",
            f"{TMUX_SESSION}:{GEMINI_WINDOW}",
            "-F",
            "#{pane_index}\t#{pane_current_command}",
        ]
    )
    if rc != 0:
        return False
    for line in out.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] == GEMINI_PANE:
            return True
    return False


async def gemini_cli_available() -> bool:
    """Check if gemini CLI is installed."""
    return shutil.which("gemini") is not None


# ---------------------------------------------------------------------------
# Gemini headless query
# ---------------------------------------------------------------------------


async def query_gemini(user_message: str) -> str:
    """Query Gemini CLI in headless pipe mode.

    Uses `gemini -p` which outputs plain text (no TUI decorations).
    Each call is stateless — no conversation history preserved.
    """
    full_prompt = f"{SYSTEM_PROMPT}\n\n---\n使用者輸入：{user_message}"

    proc = await asyncio.create_subprocess_exec(
        "gemini",
        "-p",
        full_prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=GEMINI_TIMEOUT)
    except TimeoutError:
        proc.kill()
        raise TimeoutError("Gemini CLI timed out")

    if proc.returncode != 0:
        err = (stderr or b"").decode()[:200]
        raise RuntimeError(f"Gemini CLI failed (exit {proc.returncode}): {err}")

    return _clean_gemini_output((stdout or b"").decode())


# Lines from gemini CLI stderr/hooks that leak into output
_NOISE_PATTERNS = [
    "Created execution plan for",
    "Expanding hook command:",
    "Hook execution for",
    "Loaded cached credentials",
    "Server '",
    "total duration:",
    "(cwd:",
    "MCP issues detected",
    "Run /mcp",
    "Using model:",
    "Model:",
    "I'll ",
    "Let me ",
]


def _clean_gemini_output(text: str) -> str:
    """Strip Gemini CLI noise (hook execution, server loading) from output."""
    lines = text.split("\n")
    clean = []
    for line in lines:
        if any(pat in line for pat in _NOISE_PATTERNS):
            continue
        clean.append(line)
    # Trim leading/trailing blank lines
    while clean and not clean[0].strip():
        clean.pop(0)
    while clean and not clean[-1].strip():
        clean.pop()
    return "\n".join(clean)


def extract_json_from_response(text: str) -> dict | None:
    """Extract JSON object from Gemini's response text."""
    # Try markdown code block first
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try raw JSON object
    m = _JSON_OBJECT_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Capture Console", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    pane_alive = await gemini_pane_alive()
    cli_ok = await gemini_cli_available()
    return {
        "status": "ok" if cli_ok else "degraded",
        "gemini_cli": cli_ok,
        "gemini_pane": pane_alive,
    }


@app.websocket("/ws")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    log.info("WebSocket connected")

    cli_ok = await gemini_cli_available()
    if not cli_ok:
        await ws.send_json(
            {
                "type": "error",
                "message": "Gemini CLI not found. Install with: npm i -g @anthropic/gemini-cli",
            }
        )
        await ws.close()
        return

    await ws.send_json(
        {
            "type": "status",
            "message": "已連線 Gemini 解析引擎",
            "gemini_pane": await gemini_pane_alive(),
            "gemini_ready": True,
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

            # Build the prompt with context
            context = data.get("context")
            prompt_parts = []
            if context:
                prompt_parts.append(
                    f"[補充情境: {context.get('module')}/{context.get('entity_type')}, "
                    f"缺少欄位={context.get('missing_fields', [])}, "
                    f"目前 payload={json.dumps(context.get('payload', {}), ensure_ascii=False)}]"
                )
            prompt_parts.append(text)
            full_prompt = " ".join(prompt_parts)

            # Query Gemini headless
            try:
                log.info("Querying Gemini: %s", full_prompt[:100])
                response = await query_gemini(full_prompt)

                # Send the full response as a single chunk
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
                        "text": "Gemini 回應逾時，請重試。",
                        "msg_id": msg_id,
                    }
                )
            except Exception as e:
                log.error("Gemini query failed: %s", e)
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

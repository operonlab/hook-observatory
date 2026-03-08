"""Capture Console Station — Gemini CLI pane manager + WebSocket relay."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("capture-console")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TMUX_SESSION = os.getenv("CAPTURE_TMUX_SESSION", "workshop")
GEMINI_WINDOW = os.getenv("CAPTURE_GEMINI_WINDOW", "gemini-enrichment")
POLL_INTERVAL = float(os.getenv("CAPTURE_POLL_INTERVAL", "0.35"))
HOST = os.getenv("CAPTURE_HOST", "127.0.0.1")
PORT = int(os.getenv("CAPTURE_PORT", "4104"))

SYSTEM_PROMPT = """\
You are a capture enrichment assistant for the Workshop platform.
When the user gives you a brief description, parse it into structured capture data.

ALWAYS respond with a JSON block in this format:
```json
{
  "module": "finance|taskflow|invest",
  "entity_type": "transaction|subscription|installment|task|trade",
  "payload": { ... structured fields ... },
  "confidence": 0.0-1.0,
  "notes": "any clarification"
}
```

Field reference:
- finance/transaction: type(income|expense), amount(number), description, category_id, wallet_id, payment_method(cash|credit_card|bank_transfer|e_wallet), transacted_at
- finance/subscription: name, amount, billing_cycle(monthly|yearly|weekly), start_date, wallet_id, category_id
- taskflow/task: title, description, priority(low|medium|high|urgent), due_date, source(personal|work|capture), project
- invest/trade: position_id, type(buy|sell), shares(number), price(number), traded_at, currency

Smart defaults: expense for amounts, TWD currency, credit_card payment, personal source, medium priority.
Current date context will be provided. Always respond in the user's language.
"""

# ---------------------------------------------------------------------------
# tmux helpers
# ---------------------------------------------------------------------------

async def _run(args: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "timeout"
    return proc.returncode or 0, (stdout or b"").decode(), (stderr or b"").decode()


async def pane_exists() -> bool:
    """Check if the Gemini enrichment pane exists."""
    rc, out, _ = await _run([
        "tmux", "list-windows", "-t", TMUX_SESSION, "-F", "#{window_name}",
    ])
    if rc != 0:
        return False
    return GEMINI_WINDOW in out.strip().split("\n")


async def ensure_gemini_pane() -> str:
    """Ensure the Gemini CLI pane exists. Returns the tmux target."""
    target = f"{TMUX_SESSION}:{GEMINI_WINDOW}"
    if await pane_exists():
        return target

    log.info("Creating Gemini enrichment pane: %s", target)
    # Create a new window
    rc, _, err = await _run([
        "tmux", "new-window", "-t", TMUX_SESSION, "-n", GEMINI_WINDOW, "-d",
    ])
    if rc != 0:
        log.error("Failed to create window: %s", err)
        raise RuntimeError(f"tmux new-window failed: {err}")

    # Start Gemini CLI in interactive mode
    await asyncio.sleep(0.5)
    await send_keys(target, "gemini", literal=True)
    await send_keys(target, "Enter", literal=False)

    # Wait for Gemini to start
    for _ in range(20):
        await asyncio.sleep(0.5)
        content = await capture_pane(target)
        # Gemini CLI shows a prompt like "> " or "│" when ready
        if ">" in content or "│" in content or "gemini" in content.lower():
            break

    # Send system prompt
    await send_keys(target, SYSTEM_PROMPT.replace("\n", " "), literal=True)
    await send_keys(target, "Enter", literal=False)

    # Wait for response to system prompt
    await asyncio.sleep(3)
    log.info("Gemini pane ready: %s", target)
    return target


async def send_keys(target: str, text: str, literal: bool = True) -> bool:
    args = ["tmux", "send-keys", "-t", target]
    if literal:
        args += ["-l", text]
    else:
        args.append(text)
    rc, _, _ = await _run(args)
    return rc == 0


async def capture_pane(target: str, lines: int = 100) -> str:
    rc, out, _ = await _run([
        "tmux", "capture-pane", "-t", target, "-p", "-S", f"-{lines}",
    ])
    return out if rc == 0 else ""


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Capture Console", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    has_pane = await pane_exists()
    return {"status": "ok", "gemini_pane": has_pane}


@app.websocket("/ws")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    log.info("WebSocket connected")

    # Ensure Gemini pane exists
    try:
        target = await ensure_gemini_pane()
        await ws.send_json({"type": "status", "message": "Connected to Gemini enrichment pane."})
    except Exception as e:
        await ws.send_json({"type": "error", "message": f"Failed to start Gemini: {e}"})
        await ws.close()
        return

    # Get initial pane snapshot
    last_content = await capture_pane(target)

    try:
        while True:
            # Wait for user message
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
                    f"[Context: {context.get('module')}/{context.get('entity_type')}, "
                    f"missing={context.get('missing_fields', [])}, "
                    f"current payload={json.dumps(context.get('payload', {}), ensure_ascii=False)}]"
                )
            prompt_parts.append(text)
            full_prompt = " ".join(prompt_parts)

            # Snapshot before sending
            before = await capture_pane(target)

            # Send to Gemini pane
            await send_keys(target, full_prompt, literal=True)
            await send_keys(target, "Enter", literal=False)

            # Poll for response
            stable_count = 0
            prev_new = ""
            max_polls = 120  # ~42 seconds max

            for _ in range(max_polls):
                await asyncio.sleep(POLL_INTERVAL)
                current = await capture_pane(target)

                # Extract new content (after the user's input)
                new_content = _extract_new_content(before, current, full_prompt)

                if new_content and new_content != prev_new:
                    # Send incremental chunk
                    await ws.send_json({
                        "type": "chunk",
                        "text": new_content,
                        "msg_id": msg_id,
                    })
                    prev_new = new_content
                    stable_count = 0
                elif new_content:
                    stable_count += 1

                # If content hasn't changed for ~1.4 seconds (4 polls), consider done
                if stable_count >= 4 and new_content:
                    break

            # Signal completion
            await ws.send_json({"type": "done", "msg_id": msg_id})

    except WebSocketDisconnect:
        log.info("WebSocket disconnected")
    except Exception as e:
        log.error("WebSocket error: %s", e)
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


def _extract_new_content(before: str, current: str, user_input: str) -> str:
    """Extract new content that appeared after the user's input."""
    before_lines = before.strip().split("\n")
    current_lines = current.strip().split("\n")

    # Find where the user's input appears in current
    input_start = -1
    input_short = user_input[:40]  # Use first 40 chars for matching
    for i, line in enumerate(current_lines):
        if input_short in line:
            input_start = i
            break

    if input_start < 0:
        # Try matching from the end of before content
        # Return lines that are in current but not in before
        if len(current_lines) > len(before_lines):
            new_lines = current_lines[len(before_lines):]
            return "\n".join(new_lines).strip()
        return ""

    # Everything after the input line is the response
    response_lines = current_lines[input_start + 1:]

    # Filter out the Gemini prompt characters
    cleaned = []
    for line in response_lines:
        stripped = line.strip()
        # Skip empty prompt indicators
        if stripped in (">", "│", ""):
            continue
        cleaned.append(line)

    return "\n".join(cleaned).strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")

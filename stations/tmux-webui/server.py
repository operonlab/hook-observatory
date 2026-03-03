#!/usr/bin/env python3
# /// script
# dependencies = ["fastapi", "uvicorn", "jinja2", "websockets", "python-multipart"]
# ///
"""
tmux Web Controller V2 — Modular Edition
Control multiple tmux panes from your browser with touch-friendly UX.

Usage:
    uv run stations/tmux-webui/server.py
    uv run stations/tmux-webui/server.py --port 9527 --host 127.0.0.1
"""

import argparse
import asyncio
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from autocomplete import complete, get_cache_stats, init_cache, refresh_cache
from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from tmux_manager import (
    capture_pane,
    kill_window,
    list_panes,
    list_sessions,
    list_windows,
    new_window,
    resize_pane,
    select_layout,
    select_pane,
    send_keys,
    status_metrics,
)

from config import get_config, load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tmux-webui")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = Path.home() / "workshop" / "outputs" / "tmux-webui-uploads"
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB

# ── 啟動時讀取 git hash，注入 sw.js CACHE_NAME ──


def _get_git_hash() -> str:
    """取得 workshop repo 的 git short hash，失敗時 fallback 為 'dev'。"""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", str(Path.home() / "workshop"), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "dev"


GIT_HASH = _get_git_hash()

# 讀取 sw.js 模板並替換 placeholder
_SW_JS_TEMPLATE = (BASE_DIR / "sw.js").read_text()
_SW_JS_CONTENT = _SW_JS_TEMPLATE.replace("__GIT_HASH__", GIT_HASH)

# ── Relay scripts (shared with MCP server) ──

RELAY_SCRIPTS_DIR = Path.home() / ".claude/skills/tmux-relay/scripts"
RELAY_PANE_POOL = RELAY_SCRIPTS_DIR / "pane_pool.sh"
RELAY_SH = RELAY_SCRIPTS_DIR / "relay.sh"

# ── Disconnect layout reset (debounced 10s) ──

_disconnect_timers: dict[str, asyncio.Task] = {}
_active_connections: dict[str, int] = {}  # session -> connection count


async def _reset_layout_delayed(session: str, delay: float = 10.0):
    """After delay, reset all windows in session to even-horizontal layout."""
    try:
        await asyncio.sleep(delay)
        # Only reset if no active connections remain
        if _active_connections.get(session, 0) > 0:
            return
        windows = await list_windows(session)
        for w in windows:
            target = f"{session}:{w['index']}"
            await select_layout(target, "even-horizontal")
        logger.info("Reset layout to even-horizontal for session '%s'", session)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("Reset layout error: %s", exc)
    finally:
        _disconnect_timers.pop(session, None)


def _on_ws_connect(session: str):
    """Track connection and cancel pending reset."""
    _active_connections[session] = _active_connections.get(session, 0) + 1
    timer = _disconnect_timers.pop(session, None)
    if timer:
        timer.cancel()
        logger.info("Cancelled layout reset for session '%s' (reconnected)", session)


def _on_ws_disconnect(session: str):
    """Start debounced reset timer if no connections remain."""
    count = _active_connections.get(session, 1) - 1
    _active_connections[session] = max(0, count)
    if count <= 0 and session not in _disconnect_timers:
        _disconnect_timers[session] = asyncio.create_task(_reset_layout_delayed(session))


@asynccontextmanager
async def lifespan(app):
    init_cache()
    yield


app = FastAPI(title="tmux Web Controller V2", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ── HTTP Routes ──


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    cfg = get_config()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "config": cfg,
        },
    )


@app.get("/api/sessions")
async def api_sessions():
    return await list_sessions()


@app.get("/api/sessions/{session}/panes")
async def api_panes(session: str):
    return await list_panes(session)


@app.get("/api/sessions/{session}/windows")
async def api_windows(session: str):
    return await list_windows(session)


@app.get("/api/autocomplete")
async def api_autocomplete(q: str = "", type: str = ""):
    return complete(q, type_filter=type)


@app.get("/api/autocomplete/refresh")
async def api_autocomplete_refresh():
    refresh_cache()
    return get_cache_stats()


@app.post("/api/upload")
async def api_upload(file: UploadFile):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Read file with size check
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50MB)")

    # Sanitize filename: keep only safe characters
    name = Path(file.filename).name  # strip directory components
    name = re.sub(r"[^\w\-.]", "_", name)  # replace unsafe chars
    safe_name = f"{int(time.time())}_{name}"

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / safe_name
    dest.write_bytes(content)

    logger.info("Uploaded: %s (%d bytes)", dest, len(content))
    return {"path": str(dest)}


# ── Relay dispatch ──


async def _run_relay_script(script: Path, *args: str, timeout: float = 30) -> str:
    """Run a relay shell script and return stdout."""
    proc = await asyncio.create_subprocess_exec(
        "bash",
        str(script),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise HTTPException(status_code=504, detail=f"Script timed out: {script.name}")
    if proc.returncode != 0:
        err = stderr.decode().strip()
        raise HTTPException(status_code=500, detail=f"{script.name} failed: {err}")
    return stdout.decode().strip()


@app.post("/api/relay")
async def api_relay(request: Request):
    """Dispatch a command to a relay pane (same logic as MCP relay_dispatch)."""
    body = await request.json()
    command = body.get("command", "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="command is required")
    timeout_val = body.get("timeout", 600)

    # 1. Acquire a pane
    raw = await _run_relay_script(RELAY_PANE_POOL, "acquire", "1", timeout=30)
    panes = [p.strip() for p in raw.splitlines() if p.strip()]
    if not panes:
        raise HTTPException(status_code=503, detail="No relay panes available")
    pane = panes[0]

    # 2. Check status → recycle if busy
    try:
        status = await _run_relay_script(RELAY_PANE_POOL, "status", pane, timeout=10)
    except HTTPException:
        status = "unknown"

    if status.startswith("busy"):
        try:
            await _run_relay_script(RELAY_PANE_POOL, "recycle", pane, timeout=30)
            for _ in range(10):
                await asyncio.sleep(1.5)
                try:
                    status = await _run_relay_script(
                        RELAY_PANE_POOL,
                        "status",
                        pane,
                        timeout=10,
                    )
                except HTTPException:
                    status = "unknown"
                if status == "idle":
                    break
        except HTTPException:
            raise HTTPException(status_code=503, detail=f"Cannot recycle pane {pane}")

    # 3. Dispatch (background)
    signal_file = f"/tmp/relay-webui-{int(time.time() * 1000)}-{os.getpid()}.done"
    await asyncio.create_subprocess_exec(
        "bash",
        str(RELAY_SH),
        pane,
        "",
        command,
        "--no-forward",
        "--signal",
        signal_file,
        "--timeout",
        str(timeout_val),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    logger.info("Relay dispatched to %s: %s", pane, command[:80])
    return {"pane": pane, "signal_file": signal_file}


@app.get("/api/relay/check")
async def api_relay_check(signal_file: str):
    """Check if a dispatched relay command has completed."""
    if os.path.exists(signal_file):
        return {"status": "completed", "signal_file": signal_file}
    return {"status": "running", "signal_file": signal_file}


# ── PWA assets ──


@app.get("/sw.js")
async def pwa_sw():
    from fastapi.responses import Response

    return Response(
        content=_SW_JS_CONTENT,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/manifest.json")
async def pwa_manifest():
    from fastapi.responses import FileResponse

    return FileResponse(BASE_DIR / "manifest.json", media_type="application/manifest+json")


@app.get("/icon-192.svg")
async def pwa_icon_192():
    from fastapi.responses import FileResponse

    return FileResponse(BASE_DIR / "icon-192.svg", media_type="image/svg+xml")


@app.get("/icon-512.svg")
async def pwa_icon_512():
    from fastapi.responses import FileResponse

    return FileResponse(BASE_DIR / "icon-512.svg", media_type="image/svg+xml")


# ── WebSocket handler ──


@app.websocket("/ws")
async def ws_handler(websocket: WebSocket):
    await websocket.accept()

    session = websocket.query_params.get("session", "")
    if not session:
        await websocket.send_json({"type": "error", "message": "No session specified"})
        await websocket.close()
        return

    _on_ws_connect(session)

    cfg = get_config()
    poll_interval = cfg.get("poll_interval", 0.4)
    metrics_interval = cfg.get("metrics_interval", 5.0)
    capture_lines = cfg.get("capture_lines", 150)

    all_panes = await list_panes(session)
    windows = await list_windows(session)
    if not all_panes:
        await websocket.send_json(
            {
                "type": "error",
                "message": f"No panes found in '{session}'",
            }
        )
        await websocket.close()
        return

    # Default to the tmux-active window
    active_window: int | None = None
    for w in windows:
        if w["active"]:
            active_window = w["index"]
            break

    def visible_panes(panes: list[dict]) -> list[dict]:
        if active_window is None:
            return panes
        return [p for p in panes if p["window"] == active_window]

    await websocket.send_json({"type": "windows", "windows": windows, "active": active_window})
    await websocket.send_json({"type": "panes", "panes": visible_panes(all_panes)})

    # Send initial metrics
    init_metrics = await status_metrics()
    if init_metrics:
        await websocket.send_json({"type": "metrics", "metrics": init_metrics})

    last_contents: dict[str, str] = {}
    last_metrics: dict[str, str] = dict(init_metrics)
    metrics_counter = 0
    metrics_every = max(1, int(metrics_interval / poll_interval))

    async def poll_output():
        nonlocal metrics_counter, active_window
        while True:
            try:
                current_panes = await list_panes(session)
                vis = visible_panes(current_panes)
                vis_ids = {p["id"] for p in vis}

                # Detect visible pane changes
                old_ids = set(last_contents.keys())
                if vis_ids != old_ids:
                    cur_windows = await list_windows(session)
                    await websocket.send_json(
                        {
                            "type": "windows",
                            "windows": cur_windows,
                            "active": active_window,
                        }
                    )
                    await websocket.send_json({"type": "panes", "panes": vis})
                    for gone in old_ids - vis_ids:
                        last_contents.pop(gone, None)

                updates = {}
                for p in vis:
                    target = f"{session}:{p['id']}"
                    content = await capture_pane(target, capture_lines)
                    if content != last_contents.get(p["id"]):
                        last_contents[p["id"]] = content
                        updates[p["id"]] = content

                if updates:
                    await websocket.send_json({"type": "output", "panes": updates})

                # Metrics
                metrics_counter += 1
                if metrics_counter % metrics_every == 0:
                    metrics = await status_metrics()
                    if metrics != last_metrics:
                        last_metrics.update(metrics)
                        await websocket.send_json({"type": "metrics", "metrics": metrics})

            except (WebSocketDisconnect, RuntimeError):
                break
            except Exception as exc:
                logger.error("Poll error: %s", exc)

            await asyncio.sleep(poll_interval)

    poll_task = asyncio.create_task(poll_output())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = data.get("type", "")
            pane_id = data.get("pane", "0.0")
            target = f"{session}:{pane_id}"

            if action == "input":
                text = data.get("text", "")
                if text:
                    ok = await send_keys(target, text, literal=True)
                    if ok:
                        await send_keys(target, "Enter", literal=False)
                    else:
                        await websocket.send_json(
                            {
                                "type": "input_error",
                                "message": f"Failed to send to {pane_id}",
                            }
                        )

            elif action == "key":
                key = data.get("key", "")
                mods = data.get("modifiers", [])
                ALLOWED_MODS = {"C", "M", "S", "Ctrl", "Alt", "Shift"}
                if key:
                    if mods:
                        safe_mods = [m for m in mods if m in ALLOWED_MODS]
                        if safe_mods:
                            combo = "-".join(safe_mods) + "-" + key[:8]
                        else:
                            combo = key[:8]
                        ok = await send_keys(target, combo, literal=False)
                    elif len(key) == 1 and not mods:
                        ok = await send_keys(target, key, literal=True)
                    else:
                        ok = await send_keys(target, key, literal=False)
                    if not ok:
                        await websocket.send_json(
                            {
                                "type": "input_error",
                                "message": f"Failed to send key to {pane_id}",
                            }
                        )

            elif action == "switch_window":
                win = data.get("window")
                active_window = win
                last_contents.clear()
                cur_panes = await list_panes(session)
                cur_windows = await list_windows(session)
                await websocket.send_json(
                    {
                        "type": "windows",
                        "windows": cur_windows,
                        "active": active_window,
                    }
                )
                await websocket.send_json({"type": "panes", "panes": visible_panes(cur_panes)})

            elif action == "new_window":
                await new_window(session)
                cur_windows = await list_windows(session)
                if cur_windows:
                    active_window = max(w["index"] for w in cur_windows)
                last_contents.clear()
                cur_panes = await list_panes(session)
                await websocket.send_json(
                    {
                        "type": "windows",
                        "windows": cur_windows,
                        "active": active_window,
                    }
                )
                await websocket.send_json({"type": "panes", "panes": visible_panes(cur_panes)})

            elif action == "close_window":
                win = data.get("window")
                if win is not None:
                    await kill_window(session, win)
                    cur_windows = await list_windows(session)
                    if not cur_windows:
                        await websocket.send_json(
                            {
                                "type": "error",
                                "message": "All windows closed",
                            }
                        )
                        break
                    if active_window == win:
                        active_window = cur_windows[0]["index"]
                    last_contents.clear()
                    cur_panes = await list_panes(session)
                    await websocket.send_json(
                        {
                            "type": "windows",
                            "windows": cur_windows,
                            "active": active_window,
                        }
                    )
                    await websocket.send_json(
                        {
                            "type": "panes",
                            "panes": visible_panes(cur_panes),
                        }
                    )

            elif action == "fit":
                cols = data.get("cols")
                rows = data.get("rows")
                if cols and rows:
                    await resize_pane(target, int(cols), int(rows))

            elif action == "select_pane_direction":
                direction = data.get("direction", "")
                if direction:
                    await select_pane(target, direction)

            elif action == "autocomplete":
                query = data.get("query", "")
                results = complete(query)
                await websocket.send_json(
                    {
                        "type": "autocomplete",
                        "results": results,
                    }
                )

            elif action == "refresh_panes":
                panes = await list_panes(session)
                await websocket.send_json({"type": "panes", "panes": visible_panes(panes)})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session '%s'", session)
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
    finally:
        poll_task.cancel()
        _on_ws_disconnect(session)


# ── Main ──


def main():
    parser = argparse.ArgumentParser(description="tmux Web Controller V2")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", default=None)
    args = parser.parse_args()

    cfg = load_config()
    host = args.host or cfg["host"]
    port = args.port or cfg["port"]

    logger.info("tmux Web Controller V2 (sw.js cache: tmux-webui-%s)", GIT_HASH)
    logger.info("  http://%s:%d", host, port)

    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()

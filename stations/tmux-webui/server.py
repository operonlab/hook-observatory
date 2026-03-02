#!/usr/bin/env python3
# /// script
# dependencies = ["fastapi", "uvicorn", "jinja2", "websockets"]
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
from pathlib import Path

from autocomplete import complete
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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

app = FastAPI(title="tmux Web Controller V2")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ── HTTP Routes ──


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    cfg = get_config()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "config": cfg,
    })


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
async def api_autocomplete(q: str = ""):
    return complete(q)


# ── PWA assets ──


_ICON_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {s} {s}">' \
    '<rect width="{s}" height="{s}" rx="20%" fill="#0a0a12"/>' \
    '<text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" ' \
    'font-family="monospace" font-weight="bold" font-size="{f}" fill="#8b6cef">&gt;_</text></svg>'


@app.get("/manifest.json")
async def pwa_manifest():
    return {
        "name": "tmux Web Controller",
        "short_name": "tmux",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0a12",
        "theme_color": "#0a0a12",
        "icons": [
            {"src": "/icon-192.svg", "sizes": "192x192", "type": "image/svg+xml"},
            {"src": "/icon-512.svg", "sizes": "512x512", "type": "image/svg+xml"},
        ],
    }


@app.get("/icon-192.svg")
async def pwa_icon_192():
    from fastapi.responses import Response
    return Response(content=_ICON_SVG.format(s=192, f=96), media_type="image/svg+xml")


@app.get("/icon-512.svg")
async def pwa_icon_512():
    from fastapi.responses import Response
    return Response(content=_ICON_SVG.format(s=512, f=256), media_type="image/svg+xml")


# ── WebSocket handler ──


@app.websocket("/ws")
async def ws_handler(websocket: WebSocket):
    await websocket.accept()

    session = websocket.query_params.get("session", "")
    if not session:
        await websocket.send_json({"type": "error", "message": "No session specified"})
        await websocket.close()
        return

    cfg = get_config()
    poll_interval = cfg.get("poll_interval", 0.4)
    metrics_interval = cfg.get("metrics_interval", 5.0)
    capture_lines = cfg.get("capture_lines", 150)

    all_panes = await list_panes(session)
    windows = await list_windows(session)
    if not all_panes:
        await websocket.send_json({
            "type": "error",
            "message": f"No panes found in '{session}'",
        })
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
                    await websocket.send_json({
                        "type": "windows", "windows": cur_windows, "active": active_window,
                    })
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
                        await websocket.send_json({
                            "type": "input_error",
                            "message": f"Failed to send to {pane_id}",
                        })

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
                        await websocket.send_json({
                            "type": "input_error",
                            "message": f"Failed to send key to {pane_id}",
                        })

            elif action == "switch_window":
                win = data.get("window")
                active_window = win
                last_contents.clear()
                cur_panes = await list_panes(session)
                cur_windows = await list_windows(session)
                await websocket.send_json({
                    "type": "windows", "windows": cur_windows, "active": active_window,
                })
                await websocket.send_json({"type": "panes", "panes": visible_panes(cur_panes)})

            elif action == "new_window":
                await new_window(session)
                cur_windows = await list_windows(session)
                if cur_windows:
                    active_window = max(w["index"] for w in cur_windows)
                last_contents.clear()
                cur_panes = await list_panes(session)
                await websocket.send_json({
                    "type": "windows", "windows": cur_windows, "active": active_window,
                })
                await websocket.send_json({"type": "panes", "panes": visible_panes(cur_panes)})

            elif action == "close_window":
                win = data.get("window")
                if win is not None:
                    await kill_window(session, win)
                    cur_windows = await list_windows(session)
                    if not cur_windows:
                        await websocket.send_json({
                            "type": "error", "message": "All windows closed",
                        })
                        break
                    if active_window == win:
                        active_window = cur_windows[0]["index"]
                    last_contents.clear()
                    cur_panes = await list_panes(session)
                    await websocket.send_json({
                        "type": "windows", "windows": cur_windows, "active": active_window,
                    })
                    await websocket.send_json({
                        "type": "panes", "panes": visible_panes(cur_panes),
                    })

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
                await websocket.send_json({
                    "type": "autocomplete",
                    "results": results,
                })

            elif action == "refresh_panes":
                panes = await list_panes(session)
                await websocket.send_json({"type": "panes", "panes": visible_panes(panes)})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session '%s'", session)
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
    finally:
        poll_task.cancel()


# ── Main ──


def main():
    parser = argparse.ArgumentParser(description="tmux Web Controller V2")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", default=None)
    args = parser.parse_args()

    cfg = load_config()
    host = args.host or cfg["host"]
    port = args.port or cfg["port"]

    logger.info("tmux Web Controller V2")
    logger.info("  http://%s:%d", host, port)

    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()

"""
System Monitor V2 API — standalone FastAPI station service.

Usage:
    python3 api.py                  # Start on default port 9526
    python3 api.py --port 9527      # Custom port
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

SCRIPT_DIR = Path(__file__).parent


def _load_config() -> dict:
    config_path = SCRIPT_DIR / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


CONFIG = _load_config()

REPORTS_DIR = Path(
    CONFIG.get("reports", {}).get("output_dir", "~/.claude/data/system-monitor/reports")
).expanduser()
ALERTS_DIR = Path(
    CONFIG.get("output_dir", "~/.claude/data/system-monitor")
).expanduser() / "alerts"
DATA_DIR = Path(
    CONFIG.get("output_dir", "~/.claude/data/system-monitor")
).expanduser()

app = FastAPI(title="System Monitor API", version="2.0.0")
app.mount("/static", StaticFiles(directory=SCRIPT_DIR / "static"), name="static")
templates = Jinja2Templates(directory=SCRIPT_DIR / "templates")

# Cache for latest collection
_cache: dict = {}
_cache_time: float = 0
CACHE_TTL = 30  # seconds


def _get_latest_data() -> dict:
    """Run collector and cache result."""
    import time
    global _cache, _cache_time

    now = time.time()
    if _cache and (now - _cache_time) < CACHE_TTL:
        return _cache

    try:
        from collector import collect_all, load_config
        config = load_config()
        # Hardware-only for fast status (skip slow disk scan)
        data = collect_all(config, disk=False, hardware=True)
        _cache = data
        _cache_time = now
        return data
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now(UTC).isoformat()}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the dashboard UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "ok", "service": "system-monitor", "version": "2.0.0"}


@app.get("/status")
async def status():
    """Latest hardware metrics + pressure level."""
    import asyncio
    data = await asyncio.get_event_loop().run_in_executor(None, _get_latest_data)
    return data


@app.get("/reports")
async def list_reports():
    """List all available reports."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    reports = []
    for f in sorted(REPORTS_DIR.glob("*.md"), reverse=True):
        stat = f.stat()
        reports.append({
            "filename": f.name,
            "size_bytes": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_ctime, tz=UTC).isoformat(),
        })
    return {"reports": reports, "total": len(reports)}


@app.get("/reports/{filename}", response_class=PlainTextResponse)
async def get_report(filename: str):
    """Get a single report content."""
    # Sanitize filename
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = REPORTS_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    return path.read_text(encoding="utf-8")


@app.get("/history")
async def history():
    """Historical data from saved JSON snapshots."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for f in sorted(DATA_DIR.glob("snapshot-*.json"), reverse=True)[:30]:
        try:
            data = json.loads(f.read_text())
            snapshots.append({
                "filename": f.name,
                "timestamp": data.get("timestamp"),
                "pressure_level": data.get("pressure_level"),
                "disk_usage_pct": data.get("disk", {}).get("usage_pct"),
                "cpu_usage_pct": data.get("hardware", {}).get("cpu", {}).get("usage_pct"),
                "memory_usage_pct": data.get("hardware", {}).get("memory", {}).get("usage_pct"),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return {"snapshots": snapshots, "total": len(snapshots)}


@app.get("/alerts")
async def list_alerts():
    """List recent pressure alerts."""
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    alerts = []
    for f in sorted(ALERTS_DIR.glob("alert-*.json"), reverse=True)[:20]:
        try:
            data = json.loads(f.read_text())
            alerts.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return {"alerts": alerts, "total": len(alerts)}


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="System Monitor API")
    parser.add_argument("--host", default=CONFIG.get("api", {}).get("host", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=CONFIG.get("api", {}).get("port", 9526))
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)

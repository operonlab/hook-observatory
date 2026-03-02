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
REPORTS_DIR_V1 = Path("~/Claude/disk-report").expanduser()
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

# Snapshot auto-save rate limiting
_last_snapshot_time: float = 0
SNAPSHOT_INTERVAL = 300  # 5 minutes


def _get_latest_data() -> dict:
    """Run collector and cache result."""
    import time
    global _cache, _cache_time

    now = time.time()
    if _cache and (now - _cache_time) < CACHE_TTL:
        return _cache

    try:
        from collector import collect_all, collect_disk_fast, load_config
        config = load_config()
        # Hardware + fast APFS-level disk (skip slow file scanning)
        data = collect_all(config, disk=False, hardware=True)
        data["disk"] = collect_disk_fast(config)
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


def _save_snapshot(data: dict) -> None:
    """Save a snapshot JSON for history tracking."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y-%m-%d_%H%M%S")
        path = DATA_DIR / f"snapshot-{ts}.json"
        path.write_text(json.dumps(data, ensure_ascii=False))
    except OSError:
        pass


@app.get("/status")
async def status():
    """Latest hardware metrics + pressure level. Auto-saves snapshot every 5 min."""
    import asyncio
    import time

    data = await asyncio.get_event_loop().run_in_executor(None, _get_latest_data)

    # Auto-save snapshot with rate limiting
    global _last_snapshot_time
    now = time.time()
    if now - _last_snapshot_time >= SNAPSHOT_INTERVAL:
        _last_snapshot_time = now
        _save_snapshot(data)

    return data


def _all_report_dirs() -> list[Path]:
    """Return all report directories (V2 first, then V1)."""
    dirs = [REPORTS_DIR]
    if REPORTS_DIR_V1.is_dir():
        dirs.append(REPORTS_DIR_V1)
    return dirs


@app.get("/reports")
async def list_reports():
    """List all available reports from V1 + V2 directories."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    seen = set()
    reports = []
    for d in _all_report_dirs():
        if not d.is_dir():
            continue
        for f in d.glob("*.md"):
            if f.name in seen:
                continue
            seen.add(f.name)
            stat = f.stat()
            reports.append({
                "filename": f.name,
                "size_bytes": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime, tz=UTC).isoformat(),
            })
    reports.sort(key=lambda r: r["created"], reverse=True)
    return {"reports": reports, "total": len(reports)}


@app.get("/reports/{filename}", response_class=PlainTextResponse)
async def get_report(filename: str):
    """Get a single report content (searches V2 then V1)."""
    # Sanitize filename
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    for d in _all_report_dirs():
        path = d / filename
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    raise HTTPException(status_code=404, detail="Report not found")


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

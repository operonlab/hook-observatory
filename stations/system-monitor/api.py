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

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

SCRIPT_DIR = Path(__file__).parent


def _load_config() -> dict:
    config_path = SCRIPT_DIR / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


CONFIG = _load_config()

ALERTS_DIR = Path(CONFIG.get("output_dir", "~/.claude/data/system-monitor")).expanduser() / "alerts"
DATA_DIR = Path(CONFIG.get("output_dir", "~/.claude/data/system-monitor")).expanduser()
REPORTS_DIR = Path(
    CONFIG.get("reports", {}).get("output_dir", "~/.claude/data/system-monitor/reports")
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

# Full disk scan cache (separate from status cache — much slower)
_disk_scan_cache: dict = {}
_disk_scan_time: float = 0
DISK_SCAN_CACHE_TTL = 300  # 5 minutes


class DeleteRequest(BaseModel):
    path: str
    type: str = "file"  # "file" or "directory"


class CleanCacheRequest(BaseModel):
    path: str


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


@app.get("/sw.js")
async def service_worker():
    """Serve SW from root path to maximize scope coverage."""
    sw_path = SCRIPT_DIR / "static" / "sw.js"
    return FileResponse(
        sw_path,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


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


@app.get("/services")
async def list_services():
    """List all services from plist + launcher + Docker."""
    import asyncio

    from collector import collect_services

    services = await asyncio.get_event_loop().run_in_executor(None, collect_services)
    return {"services": services, "total": len(services)}


@app.post("/services/{label:path}/enable")
async def enable_service(label: str):
    """Enable (launchctl load) a service by label."""
    import subprocess

    agents_dir = Path.home() / "Library" / "LaunchAgents"

    # Find plist (could be .plist.disabled)
    disabled_path = None
    enabled_path = None
    for p in agents_dir.iterdir():
        if not p.name.endswith((".plist", ".plist.disabled")):
            continue
        try:
            import plistlib

            with open(p, "rb") as f:
                plist = plistlib.load(f)
            if plist.get("Label") == label:
                if p.name.endswith(".disabled"):
                    disabled_path = p
                else:
                    enabled_path = p
                break
        except Exception:
            continue

    if disabled_path:
        # Rename .plist.disabled → .plist
        new_path = disabled_path.parent / disabled_path.name.replace(".plist.disabled", ".plist")
        disabled_path.rename(new_path)
        enabled_path = new_path

    if not enabled_path:
        raise HTTPException(status_code=404, detail=f"找不到服務: {label}")

    result = subprocess.run(
        ["launchctl", "load", str(enabled_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return {"status": "error", "label": label, "detail": result.stderr.strip()}
    return {"status": "ok", "label": label, "action": "enabled"}


@app.post("/services/{label:path}/disable")
async def disable_service(label: str):
    """Disable (launchctl unload) a service by label."""
    import subprocess

    agents_dir = Path.home() / "Library" / "LaunchAgents"

    plist_path = None
    for p in agents_dir.glob("*.plist"):
        try:
            import plistlib

            with open(p, "rb") as f:
                plist = plistlib.load(f)
            if plist.get("Label") == label:
                plist_path = p
                break
        except Exception:
            continue

    if not plist_path:
        raise HTTPException(status_code=404, detail=f"找不到服務: {label}")

    result = subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return {"status": "error", "label": label, "detail": result.stderr.strip()}

    # Rename to .disabled
    disabled_path = plist_path.parent / (plist_path.name + ".disabled")
    plist_path.rename(disabled_path)
    return {"status": "ok", "label": label, "action": "disabled"}


@app.post("/services/{label:path}/restart")
async def restart_service(label: str):
    """Restart a launchd service (unload + load)."""
    import subprocess

    agents_dir = Path.home() / "Library" / "LaunchAgents"

    plist_path = None
    for p in agents_dir.glob("*.plist"):
        try:
            import plistlib

            with open(p, "rb") as f:
                plist = plistlib.load(f)
            if plist.get("Label") == label:
                plist_path = p
                break
        except Exception:
            continue

    if not plist_path:
        raise HTTPException(status_code=404, detail=f"找不到服務: {label}")

    # Unload
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    # Load
    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return {"status": "error", "label": label, "detail": result.stderr.strip()}
    return {"status": "ok", "label": label, "action": "restarted"}


@app.get("/services/{label:path}/logs")
async def service_logs(label: str, lines: int = 50):
    """Get recent log lines for a service."""
    import asyncio

    from collector import get_service_logs

    data = await asyncio.get_event_loop().run_in_executor(
        None, lambda: get_service_logs(label, lines)
    )
    return data


@app.get("/guardian")
async def guardian_log():
    """Get memory guardian action log."""
    from collector import collect_guardian_log

    entries = collect_guardian_log()
    return {"entries": entries, "total": len(entries)}


@app.get("/history")
async def history():
    """Historical data from saved JSON snapshots."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for f in sorted(DATA_DIR.glob("snapshot-*.json"), reverse=True)[:30]:
        try:
            data = json.loads(f.read_text())
            snapshots.append(
                {
                    "filename": f.name,
                    "timestamp": data.get("timestamp"),
                    "pressure_level": data.get("pressure_level"),
                    "disk_usage_pct": data.get("disk", {}).get("usage_pct"),
                    "cpu_usage_pct": data.get("hardware", {}).get("cpu", {}).get("usage_pct"),
                    "memory_usage_pct": data.get("hardware", {}).get("memory", {}).get("usage_pct"),
                }
            )
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


# ---------------------------------------------------------------------------
# Disk Management Endpoints
# ---------------------------------------------------------------------------


@app.get("/disk/summary")
async def disk_summary():
    """Lightweight disk summary via APFS-level query (~1s)."""
    import asyncio

    from collector import collect_disk_fast, load_config

    config = load_config()
    data = await asyncio.get_event_loop().run_in_executor(None, lambda: collect_disk_fast(config))
    return data


@app.get("/disk/scan")
async def disk_scan():
    """Full disk scan including large files, stale files, caches (~30s, cached 5min)."""
    import asyncio
    import time

    global _disk_scan_cache, _disk_scan_time

    now = time.time()
    if _disk_scan_cache and (now - _disk_scan_time) < DISK_SCAN_CACHE_TTL:
        return _disk_scan_cache

    from collector import collect_disk, load_config

    config = load_config()
    data = await asyncio.get_event_loop().run_in_executor(None, lambda: collect_disk(config))
    _disk_scan_cache = data
    _disk_scan_time = time.time()
    return data


@app.post("/disk/delete")
async def disk_delete(req: DeleteRequest):
    """Delete a file or directory with safety validation."""
    from disk_manager import DiskManager

    mgr = DiskManager()
    try:
        result = mgr.delete_file(req.path, req.type)
        return result
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e)) from None
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@app.post("/disk/clean-cache")
async def disk_clean_cache(req: CleanCacheRequest):
    """Clean all contents of a cache directory."""
    from disk_manager import DiskManager

    mgr = DiskManager()
    try:
        result = mgr.clean_cache_dir(req.path)
        return result
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e)) from None
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@app.post("/disk/empty-trash")
async def disk_empty_trash():
    """Empty the user's Trash directory."""
    from disk_manager import DiskManager

    mgr = DiskManager()
    result = mgr.empty_trash()
    return result


# ---------------------------------------------------------------------------
# Reports Endpoints
# ---------------------------------------------------------------------------


@app.get("/reports")
async def list_reports(
    report_type: str | None = Query(None, alias="type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List generated reports (Markdown files), with optional type filter and pagination."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    all_files = sorted(REPORTS_DIR.glob("*.md"), reverse=True)

    if report_type:
        all_files = [f for f in all_files if report_type in f.stem]

    total = len(all_files)
    page = all_files[offset : offset + limit]

    reports = []
    for f in page:
        stat = f.stat()
        reports.append(
            {
                "filename": f.name,
                "size_bytes": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                "type": (
                    "monthly"
                    if "monthly" in f.stem
                    else "weekly"
                    if "weekly" in f.stem
                    else "daily"
                ),
            }
        )
    return {"reports": reports, "total": total}


@app.get("/reports/{filename}")
async def get_report(filename: str):
    """Read a specific report file (Markdown)."""
    # Sanitize filename to prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    report_path = REPORTS_DIR / filename
    if not report_path.exists():
        raise HTTPException(status_code=404, detail=f"Report not found: {filename}")

    content = report_path.read_text(encoding="utf-8")
    return {"filename": filename, "content": content}


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="System Monitor API")
    parser.add_argument("--host", default=CONFIG.get("api", {}).get("host", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=CONFIG.get("api", {}).get("port", 9526))
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)

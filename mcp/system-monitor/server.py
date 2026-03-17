"""System Monitor MCP Server -- hardware monitoring tools for Claude Code.

6 tools: sysmon_status, sysmon_services, sysmon_disk_summary, sysmon_disk_scan,
         sysmon_alerts, sysmon_reports.

Usage (via .mcp.json):
    uv run --no-project --with 'mcp>=1.0' --with httpx python3 mcp/system-monitor/server.py
"""

import json
from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients.system_monitor import SystemMonitorClient
from workshop.mcp_helpers import mcp_error_handler

mcp = FastMCP("system-monitor")
client = SystemMonitorClient()

# -- Response size limits --
_MAX_HISTORY = 10
_MAX_SERVICES = 30
_MAX_LOG_LINES = 30
_MAX_LARGE_FILES = 20
_MAX_CACHES = 15
_MAX_STALE_FILES = 15
_MAX_ALERTS = 10
_MAX_GUARDIAN = 10
_MAX_REPORTS = 10
_MAX_REPORT_CONTENT_LEN = 3000


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _truncate(s: str | None, maxlen: int) -> str | None:
    if s and len(s) > maxlen:
        return s[:maxlen] + f"\n... (truncated, {len(s)} chars total)"
    return s


def _slim_service(svc: dict) -> dict:
    """Keep only MCP-relevant fields for a service entry."""
    return {k: svc[k] for k in ("label", "type", "status", "pid") if k in svc}


@mcp.tool()
@mcp_error_handler("SystemMonitor")
async def sysmon_status(include_history: bool = False) -> str:
    """Get current system status -- CPU, memory, disk usage percentages and pressure level. Optionally include historical snapshots."""
    status = await to_thread(client.get_status)
    if include_history:
        history = await to_thread(client.get_history)
        snapshots = history.get("snapshots", [])
        total = len(snapshots)
        status["history"] = snapshots[:_MAX_HISTORY]
        status["history_total"] = total
        if total > _MAX_HISTORY:
            status["history_truncated"] = f"Showing {_MAX_HISTORY}/{total} snapshots"
    return json_text(status)


@mcp.tool()
@mcp_error_handler("SystemMonitor")
async def sysmon_services(
    label: str = "",
    lines: int = _MAX_LOG_LINES,
    limit: int = _MAX_SERVICES,
) -> str:
    """List all system services (launchd, plist, Docker) with their status, type, and PID. Can also fetch logs for a specific service."""
    if label:
        lines = min(lines, _MAX_LOG_LINES)
        result = await to_thread(client.get_service_logs, label, lines)
    else:
        limit = min(limit, _MAX_SERVICES)
        result = await to_thread(client.list_services)
        services = result.get("services", [])
        total = len(services)
        result["services"] = [_slim_service(s) for s in services[:limit]]
        result["total"] = total
        if total > limit:
            result["truncated"] = f"Showing {limit}/{total} services"
    return json_text(result)


@mcp.tool()
@mcp_error_handler("SystemMonitor")
async def sysmon_disk_summary() -> str:
    """Quick disk usage summary -- total, used, free space and volume breakdown (~1s)."""
    result = await to_thread(client.disk_summary)
    return json_text(result)


@mcp.tool()
@mcp_error_handler("SystemMonitor")
async def sysmon_disk_scan(limit: int = _MAX_LARGE_FILES) -> str:
    """Full disk scan -- large files, caches, reclaimable space. Takes ~30s but cached for 5 minutes."""
    limit = min(limit, _MAX_LARGE_FILES)
    result = await to_thread(client.disk_scan)
    # Truncate each list-type category
    for key in ("large_files", "stale_files", "caches", "reclaimable"):
        if key in result and isinstance(result[key], list):
            total = len(result[key])
            cap = _MAX_CACHES if key == "caches" else limit
            result[key] = result[key][:cap]
            if total > cap:
                result[f"{key}_total"] = total
    # Remove raw path fields that aren't useful for MCP consumers
    for key in ("large_files", "stale_files"):
        for item in result.get(key, []):
            item.pop("full_path", None)
    return json_text(result)


@mcp.tool()
@mcp_error_handler("SystemMonitor")
async def sysmon_alerts(include_guardian: bool = False, limit: int = _MAX_ALERTS) -> str:
    """List recent pressure alerts (memory/disk/CPU warnings) and memory guardian logs."""
    limit = min(limit, _MAX_ALERTS)
    alerts = await to_thread(client.list_alerts)
    alert_list = alerts.get("alerts", [])
    total_alerts = len(alert_list)
    alerts["alerts"] = alert_list[:limit]
    alerts["total"] = total_alerts
    if total_alerts > limit:
        alerts["truncated"] = f"Showing {limit}/{total_alerts} alerts"

    if include_guardian:
        guardian = await to_thread(client.get_guardian_log)
        entries = guardian.get("entries", [])
        total_entries = len(entries)
        alerts["guardian"] = entries[:_MAX_GUARDIAN]
        alerts["guardian_total"] = total_entries
        if total_entries > _MAX_GUARDIAN:
            alerts["guardian_truncated"] = (
                f"Showing {_MAX_GUARDIAN}/{total_entries} entries"
            )
    return json_text(alerts)


@mcp.tool()
@mcp_error_handler("SystemMonitor")
async def sysmon_reports(
    filename: str = "",
    type: str = "",
    limit: int = _MAX_REPORTS,
) -> str:
    """List or read system monitor reports (daily/weekly/monthly markdown reports)."""
    if filename:
        result = await to_thread(client.get_report, filename)
        # Truncate long report content
        if "content" in result:
            result["content"] = _truncate(result["content"], _MAX_REPORT_CONTENT_LEN)
    else:
        rtype = type or None
        limit = min(limit, _MAX_REPORTS)
        result = await to_thread(client.list_reports, rtype, limit)
    return json_text(result)


if __name__ == "__main__":
    mcp.run()

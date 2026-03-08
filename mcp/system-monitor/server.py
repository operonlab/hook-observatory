"""System Monitor MCP Server -- hardware monitoring tools for Claude Code.

6 tools: sysmon_status, sysmon_services, sysmon_disk_summary, sysmon_disk_scan,
         sysmon_alerts, sysmon_reports.

Usage (via .mcp.json):
    uv run --no-project --with 'mcp>=1.0' --with httpx python3 mcp/system-monitor/server.py
"""

import asyncio
import json
from asyncio import to_thread

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients.system_monitor import SystemMonitorClient, SystemMonitorError

server = Server("system-monitor")
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


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _truncate(s: str | None, maxlen: int) -> str | None:
    if s and len(s) > maxlen:
        return s[:maxlen] + f"\n... (truncated, {len(s)} chars total)"
    return s


def _slim_service(svc: dict) -> dict:
    """Keep only MCP-relevant fields for a service entry."""
    return {k: svc[k] for k in ("label", "type", "status", "pid") if k in svc}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="sysmon_status",
            description=(
                "Get current system status -- CPU, memory, disk usage percentages "
                "and pressure level. Optionally include historical snapshots."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "include_history": {
                        "type": "boolean",
                        "default": False,
                        "description": f"Include historical snapshots (max {_MAX_HISTORY})",
                    },
                },
            },
        ),
        Tool(
            name="sysmon_services",
            description=(
                "List all system services (launchd, plist, Docker) with their status, "
                "type, and PID. Can also fetch logs for a specific service."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "Service label to get logs for (optional)",
                    },
                    "lines": {
                        "type": "integer",
                        "default": _MAX_LOG_LINES,
                        "description": f"Number of log lines (when label is provided, max {_MAX_LOG_LINES})",
                    },
                    "limit": {
                        "type": "integer",
                        "default": _MAX_SERVICES,
                        "description": "Max services to list",
                    },
                },
            },
        ),
        Tool(
            name="sysmon_disk_summary",
            description="Quick disk usage summary -- total, used, free space and volume breakdown (~1s).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="sysmon_disk_scan",
            description=(
                "Full disk scan -- large files, caches, reclaimable space. "
                "Takes ~30s but cached for 5 minutes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": _MAX_LARGE_FILES,
                        "description": "Max items per category (large_files, caches, etc.)",
                    },
                },
            },
        ),
        Tool(
            name="sysmon_alerts",
            description="List recent pressure alerts (memory/disk/CPU warnings) and memory guardian logs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_guardian": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include memory guardian operation log",
                    },
                    "limit": {
                        "type": "integer",
                        "default": _MAX_ALERTS,
                        "description": "Max alerts to return",
                    },
                },
            },
        ),
        Tool(
            name="sysmon_reports",
            description="List or read system monitor reports (daily/weekly/monthly markdown reports).",
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Report filename to read (if omitted, lists reports)",
                    },
                    "type": {
                        "type": "string",
                        "description": "Filter by report type: daily, weekly, monthly",
                    },
                    "limit": {
                        "type": "integer",
                        "default": _MAX_REPORTS,
                        "description": "Max reports to list",
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        match name:
            case "sysmon_status":
                status = await to_thread(client.get_status)
                if arguments.get("include_history"):
                    history = await to_thread(client.get_history)
                    snapshots = history.get("snapshots", [])
                    total = len(snapshots)
                    status["history"] = snapshots[:_MAX_HISTORY]
                    status["history_total"] = total
                    if total > _MAX_HISTORY:
                        status["history_truncated"] = f"Showing {_MAX_HISTORY}/{total} snapshots"
                return text_result(json_text(status))

            case "sysmon_services":
                label = arguments.get("label")
                if label:
                    lines = min(arguments.get("lines", _MAX_LOG_LINES), _MAX_LOG_LINES)
                    result = await to_thread(client.get_service_logs, label, lines)
                else:
                    limit = min(arguments.get("limit", _MAX_SERVICES), _MAX_SERVICES)
                    result = await to_thread(client.list_services)
                    services = result.get("services", [])
                    total = len(services)
                    result["services"] = [_slim_service(s) for s in services[:limit]]
                    result["total"] = total
                    if total > limit:
                        result["truncated"] = f"Showing {limit}/{total} services"
                return text_result(json_text(result))

            case "sysmon_disk_summary":
                result = await to_thread(client.disk_summary)
                return text_result(json_text(result))

            case "sysmon_disk_scan":
                limit = min(arguments.get("limit", _MAX_LARGE_FILES), _MAX_LARGE_FILES)
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
                return text_result(json_text(result))

            case "sysmon_alerts":
                limit = min(arguments.get("limit", _MAX_ALERTS), _MAX_ALERTS)
                alerts = await to_thread(client.list_alerts)
                alert_list = alerts.get("alerts", [])
                total_alerts = len(alert_list)
                alerts["alerts"] = alert_list[:limit]
                alerts["total"] = total_alerts
                if total_alerts > limit:
                    alerts["truncated"] = f"Showing {limit}/{total_alerts} alerts"

                if arguments.get("include_guardian"):
                    guardian = await to_thread(client.get_guardian_log)
                    entries = guardian.get("entries", [])
                    total_entries = len(entries)
                    alerts["guardian"] = entries[:_MAX_GUARDIAN]
                    alerts["guardian_total"] = total_entries
                    if total_entries > _MAX_GUARDIAN:
                        alerts["guardian_truncated"] = (
                            f"Showing {_MAX_GUARDIAN}/{total_entries} entries"
                        )
                return text_result(json_text(alerts))

            case "sysmon_reports":
                filename = arguments.get("filename")
                if filename:
                    result = await to_thread(client.get_report, filename)
                    # Truncate long report content
                    if "content" in result:
                        result["content"] = _truncate(result["content"], _MAX_REPORT_CONTENT_LEN)
                else:
                    rtype = arguments.get("type")
                    limit = min(arguments.get("limit", _MAX_REPORTS), _MAX_REPORTS)
                    result = await to_thread(client.list_reports, rtype, limit)
                return text_result(json_text(result))

            case _:
                return text_result(f"Unknown tool: {name}")

    except SystemMonitorError as e:
        return text_result(f"System Monitor API error ({e.status_code}): {e.detail}")
    except Exception as e:
        return text_result(f"Error: {type(e).__name__}: {e}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

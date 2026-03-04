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


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


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
                        "description": "Include historical snapshots (max 30)",
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
                        "default": 50,
                        "description": "Number of log lines (when label is provided)",
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
            inputSchema={"type": "object", "properties": {}},
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
                        "default": 20,
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
                    status["history"] = history.get("snapshots", [])
                return text_result(json_text(status))

            case "sysmon_services":
                label = arguments.get("label")
                if label:
                    lines = arguments.get("lines", 50)
                    result = await to_thread(client.get_service_logs, label, lines)
                else:
                    result = await to_thread(client.list_services)
                return text_result(json_text(result))

            case "sysmon_disk_summary":
                result = await to_thread(client.disk_summary)
                return text_result(json_text(result))

            case "sysmon_disk_scan":
                result = await to_thread(client.disk_scan)
                return text_result(json_text(result))

            case "sysmon_alerts":
                alerts = await to_thread(client.list_alerts)
                if arguments.get("include_guardian"):
                    guardian = await to_thread(client.get_guardian_log)
                    alerts["guardian"] = guardian.get("entries", [])
                return text_result(json_text(alerts))

            case "sysmon_reports":
                filename = arguments.get("filename")
                if filename:
                    result = await to_thread(client.get_report, filename)
                else:
                    rtype = arguments.get("type")
                    limit = arguments.get("limit", 20)
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

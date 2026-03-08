"""Sentinel MCP Server -- health monitoring tools for Claude Code.

5 tools: sentinel_status, sentinel_service, sentinel_incidents,
         sentinel_operations, sentinel_uptime.

Usage (via .mcp.json):
    uv run --no-project --with 'mcp>=1.0' --with httpx python3 mcp/sentinel/server.py
"""

import asyncio
import json
from asyncio import to_thread

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients.sentinel import SentinelClient, SentinelError

server = Server("sentinel")
client = SentinelClient()

# -- Response size limits --
_MAX_SERVICES = 30
_MAX_INCIDENTS = 10
_MAX_OPERATIONS = 20
_MAX_UPTIME_DAYS = 14
_MAX_UPTIME_SERVICES = 20
_MAX_DETAIL_LEN = 200


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _truncate(s: str | None, maxlen: int = _MAX_DETAIL_LEN) -> str | None:
    if s and len(s) > maxlen:
        return s[:maxlen] + "..."
    return s


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="sentinel_status",
            description=(
                "Get Sentinel overall status dashboard -- shows all monitored services "
                "with their health status, response times, and last check time."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": _MAX_SERVICES,
                        "description": "Max services to return",
                    },
                },
            },
        ),
        Tool(
            name="sentinel_service",
            description="Get detailed status of a single monitored service.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Service name (e.g. nginx, postgres, core, frontend)",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="sentinel_incidents",
            description="List recent incidents with service, severity, status, and timestamps.",
            inputSchema={
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "default": 1, "description": "Page number"},
                    "limit": {
                        "type": "integer",
                        "default": _MAX_INCIDENTS,
                        "description": "Page size (max 20)",
                    },
                },
            },
        ),
        Tool(
            name="sentinel_operations",
            description="List active agent operations (agents currently working on services).",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": _MAX_OPERATIONS,
                        "description": "Max operations to return",
                    },
                },
            },
        ),
        Tool(
            name="sentinel_uptime",
            description="Get per-service uptime percentages over a time period.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "default": _MAX_UPTIME_DAYS,
                        "description": f"Number of days to look back (default {_MAX_UPTIME_DAYS}, max 365)",
                    },
                    "limit": {
                        "type": "integer",
                        "default": _MAX_UPTIME_SERVICES,
                        "description": "Max services to include",
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        match name:
            case "sentinel_status":
                limit = min(arguments.get("limit", _MAX_SERVICES), _MAX_SERVICES)
                result = await to_thread(client.get_status_summary)
                services = result.get("services", [])
                total = len(services)
                result["services"] = services[:limit]
                result["total_services"] = total
                if total > limit:
                    result["truncated"] = f"Showing {limit}/{total} services"
                return text_result(json_text(result))

            case "sentinel_service":
                svc = arguments.get("name", "")
                result = await to_thread(client.get_service_status, svc)
                return text_result(json_text(result))

            case "sentinel_incidents":
                page = arguments.get("page", 1)
                limit = min(arguments.get("limit", _MAX_INCIDENTS), 20)
                result = await to_thread(client.list_incidents, page, limit)
                # Truncate long detail fields in each incident
                for item in result.get("items", []):
                    if "detail" in item:
                        item["detail"] = _truncate(item["detail"])
                return text_result(json_text(result))

            case "sentinel_operations":
                limit = min(arguments.get("limit", _MAX_OPERATIONS), _MAX_OPERATIONS)
                result = await to_thread(client.list_operations)
                # result is a list from the API
                items = result if isinstance(result, list) else result.get("items", [])
                total = len(items)
                output = {
                    "total_count": total,
                    "items": items[:limit],
                }
                if total > limit:
                    output["truncated"] = f"Showing {limit}/{total} operations"
                return text_result(json_text(output))

            case "sentinel_uptime":
                days = min(arguments.get("days", _MAX_UPTIME_DAYS), 365)
                svc_limit = min(arguments.get("limit", _MAX_UPTIME_SERVICES), _MAX_UPTIME_SERVICES)
                result = await to_thread(client.get_uptime, days)
                services = result.get("services", [])
                total_svcs = len(services)
                # Limit number of services
                services = services[:svc_limit]
                # Limit days per service (keep most recent)
                for svc in services:
                    day_list = svc.get("days", [])
                    if len(day_list) > _MAX_UPTIME_DAYS:
                        svc["days"] = day_list[-_MAX_UPTIME_DAYS:]
                        svc["days_truncated"] = (
                            f"Showing last {_MAX_UPTIME_DAYS} of {len(day_list)} days"
                        )
                result["services"] = services
                result["total_services"] = total_svcs
                if total_svcs > svc_limit:
                    result["truncated"] = f"Showing {svc_limit}/{total_svcs} services"
                return text_result(json_text(result))

            case _:
                return text_result(f"Unknown tool: {name}")

    except SentinelError as e:
        return text_result(f"Sentinel API error ({e.status_code}): {e.detail}")
    except Exception as e:
        return text_result(f"Error: {type(e).__name__}: {e}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

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


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="sentinel_status",
            description=(
                "Get Sentinel overall status dashboard -- shows all monitored services "
                "with their health status, response times, and last check time."
            ),
            inputSchema={"type": "object", "properties": {}},
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
                    "limit": {"type": "integer", "default": 20, "description": "Page size"},
                },
            },
        ),
        Tool(
            name="sentinel_operations",
            description="List active agent operations (agents currently working on services).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="sentinel_uptime",
            description="Get per-service uptime percentages over a time period.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "default": 90,
                        "description": "Number of days to look back (max 365)",
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
                result = await to_thread(client.get_status_summary)
                return text_result(json_text(result))

            case "sentinel_service":
                svc = arguments.get("name", "")
                result = await to_thread(client.get_service_status, svc)
                return text_result(json_text(result))

            case "sentinel_incidents":
                page = arguments.get("page", 1)
                limit = arguments.get("limit", 20)
                result = await to_thread(client.list_incidents, page, limit)
                return text_result(json_text(result))

            case "sentinel_operations":
                result = await to_thread(client.list_operations)
                return text_result(json_text(result))

            case "sentinel_uptime":
                days = arguments.get("days", 90)
                result = await to_thread(client.get_uptime, days)
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

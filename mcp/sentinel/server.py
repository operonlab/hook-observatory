"""Sentinel MCP Server -- health monitoring tools for Claude Code.

5 tools: sentinel_status, sentinel_service, sentinel_incidents,
         sentinel_operations, sentinel_uptime.

Usage (via .mcp.json):
    uv run --no-project --with 'mcp>=1.0' --with httpx python3 mcp/sentinel/server.py
"""

import json
from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients.sentinel import SentinelClient
from workshop.mcp_helpers import mcp_error_handler

mcp = FastMCP("sentinel")
client = SentinelClient()

# -- Response size limits --
_MAX_SERVICES = 30
_MAX_INCIDENTS = 10
_MAX_OPERATIONS = 20
_MAX_UPTIME_DAYS = 14
_MAX_UPTIME_SERVICES = 20
_MAX_DETAIL_LEN = 200


def json_text(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _truncate(s: str | None, maxlen: int = _MAX_DETAIL_LEN) -> str | None:
    if s and len(s) > maxlen:
        return s[:maxlen] + "..."
    return s


@mcp.tool()
@mcp_error_handler("Sentinel")
async def sentinel_status(limit: int = _MAX_SERVICES) -> str:
    """Get Sentinel overall status dashboard -- shows all monitored services with their health status, response times, and last check time."""
    limit = min(limit, _MAX_SERVICES)
    result = await to_thread(client.get_status_summary)
    services = result.get("services", [])
    total = len(services)
    result["services"] = services[:limit]
    result["total_services"] = total
    if total > limit:
        result["truncated"] = f"Showing {limit}/{total} services"
    return json_text(result)


@mcp.tool()
@mcp_error_handler("Sentinel")
async def sentinel_service(name: str) -> str:
    """Get detailed status of a single monitored service."""
    result = await to_thread(client.get_service_status, name)
    return json_text(result)


@mcp.tool()
@mcp_error_handler("Sentinel")
async def sentinel_incidents(page: int = 1, limit: int = _MAX_INCIDENTS) -> str:
    """List recent incidents with service, severity, status, and timestamps."""
    limit = min(limit, 20)
    result = await to_thread(client.list_incidents, page, limit)
    # Truncate long detail fields in each incident
    for item in result.get("items", []):
        if "detail" in item:
            item["detail"] = _truncate(item["detail"])
    return json_text(result)


@mcp.tool()
@mcp_error_handler("Sentinel")
async def sentinel_operations(limit: int = _MAX_OPERATIONS) -> str:
    """List active agent operations (agents currently working on services)."""
    limit = min(limit, _MAX_OPERATIONS)
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
    return json_text(output)


@mcp.tool()
@mcp_error_handler("Sentinel")
async def sentinel_uptime(days: int = _MAX_UPTIME_DAYS, limit: int = _MAX_UPTIME_SERVICES) -> str:
    """Get per-service uptime percentages over a time period."""
    days = min(days, 365)
    svc_limit = min(limit, _MAX_UPTIME_SERVICES)
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
    return json_text(result)


if __name__ == "__main__":
    mcp.run()

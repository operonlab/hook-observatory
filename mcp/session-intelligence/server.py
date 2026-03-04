#!/Users/joneshong/.local/bin/python3
"""Session Intelligence MCP Server — 6 analytics tools.

Tools:
    session_intel_stats     — session statistics (params: days)
    session_intel_sessions  — list recent sessions (params: days, project)
    session_intel_patterns  — pattern analysis (params: days)
    session_intel_trends    — productivity trends (params: weeks)
    session_intel_digest    — weekly digest (params: week_offset)
    session_intel_security  — security report (params: days)

Configure in ~/.claude.json:
    "session-intelligence": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/session-intelligence/server.py"],
        "env": {}
    }
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "libs", "python", "src"))

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from workshop.clients.session_intelligence import SessionIntelligenceClient

server = Server("workshop-session-intelligence")
_client = SessionIntelligenceClient()


def _text(content: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=content)]


def _json_text(data) -> list[types.TextContent]:
    return _text(json.dumps(data, ensure_ascii=False, default=str, indent=2))


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="session_intel_stats",
            description=(
                "Aggregate Claude Code session statistics over the past N days. "
                "Returns total sessions, messages, avg session length, size, "
                "active projects count, sessions-by-day breakdown, and redaction stats."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "default": 30,
                        "description": "Look-back period in days (default: 30)",
                    },
                },
            },
        ),
        types.Tool(
            name="session_intel_sessions",
            description=(
                "List recent Claude Code sessions with metadata. "
                "Returns session_id, project, size_bytes, message count, "
                "created_at, modified_at, and redaction count per session."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "default": 7,
                        "description": "Look-back period in days (default: 7)",
                    },
                    "project": {
                        "type": "string",
                        "description": "Filter by project directory name (partial match, optional)",
                    },
                },
            },
        ),
        types.Tool(
            name="session_intel_patterns",
            description=(
                "Detect usage patterns in Claude Code sessions. "
                "Returns peak hours, avg daily sessions, common projects, "
                "session length distribution, and redaction category hotspots."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "default": 30,
                        "description": "Look-back period in days (default: 30)",
                    },
                },
            },
        ),
        types.Tool(
            name="session_intel_trends",
            description=(
                "Weekly productivity trends for Claude Code usage. "
                "Returns per-ISO-week metrics: sessions_count, total_messages, "
                "avg_session_length, unique_projects, redactions_count."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "weeks": {
                        "type": "integer",
                        "default": 4,
                        "description": "Number of weeks to analyze (default: 4)",
                    },
                },
            },
        ),
        types.Tool(
            name="session_intel_digest",
            description=(
                "Generate a weekly digest of Claude Code session activity. "
                "Includes summary stats, top projects, notable sessions, "
                "security report, and comparison vs previous week."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "week_offset": {
                        "type": "integer",
                        "default": 0,
                        "description": "0=current week, 1=last week, 2=two weeks ago, etc.",
                    },
                },
            },
        ),
        types.Tool(
            name="session_intel_security",
            description=(
                "Security-focused report on sensitive data detection across sessions. "
                "Returns total redactions, category breakdown, daily trend, "
                "most affected projects, and list of unprocessed sessions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "default": 30,
                        "description": "Look-back period in days (default: 30)",
                    },
                },
            },
        ),
    ]


# ======================== Tool Handler ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "session_intel_stats":
            days = int(arguments.get("days", 30))
            result = await asyncio.to_thread(_client.session_stats, days=days)
            return _json_text(result)

        elif name == "session_intel_sessions":
            days = int(arguments.get("days", 7))
            project = arguments.get("project") or None
            result = await asyncio.to_thread(_client.session_list, days=days, project=project)
            return _json_text(result)

        elif name == "session_intel_patterns":
            days = int(arguments.get("days", 30))
            result = await asyncio.to_thread(_client.pattern_analysis, days=days)
            return _json_text(result)

        elif name == "session_intel_trends":
            weeks = int(arguments.get("weeks", 4))
            result = await asyncio.to_thread(_client.productivity_trends, weeks=weeks)
            return _json_text(result)

        elif name == "session_intel_digest":
            week_offset = int(arguments.get("week_offset", 0))
            result = await asyncio.to_thread(_client.weekly_digest, week_offset=week_offset)
            return _json_text(result)

        elif name == "session_intel_security":
            days = int(arguments.get("days", 30))
            result = await asyncio.to_thread(_client.security_report, days=days)
            return _json_text(result)

        return _text(f"Unknown tool: {name}")

    except Exception as exc:
        return _text(f"session-intelligence error [{name}]: {exc}")


# ======================== Main ========================


async def main() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())

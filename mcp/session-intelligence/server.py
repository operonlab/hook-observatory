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

from mcp.server.fastmcp import FastMCP
from workshop.clients.session_intelligence import SessionIntelligenceClient

mcp = FastMCP("workshop-session-intelligence")
_client = SessionIntelligenceClient()


# ======================== Tools ========================


@mcp.tool()
async def session_intel_stats(days: int = 30) -> str:
    """Aggregate Claude Code session statistics over the past N days. Returns total sessions, messages, avg session length, size, active projects count, sessions-by-day breakdown, and redaction stats."""
    try:
        result = await asyncio.to_thread(_client.session_stats, days=days)
        return json.dumps(result, ensure_ascii=False, default=str, indent=2)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def session_intel_sessions(days: int = 7, project: str | None = None, limit: int = 20) -> str:
    """List recent Claude Code sessions with metadata. Returns session_id, project, size_bytes, message count, created_at, modified_at, and redaction count per session."""
    try:
        result = await asyncio.to_thread(
            _client.session_list, days=days, project=project or None, limit=limit
        )
        return json.dumps(result, ensure_ascii=False, default=str, indent=2)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def session_intel_patterns(days: int = 30) -> str:
    """Detect usage patterns in Claude Code sessions. Returns peak hours, avg daily sessions, common projects, session length distribution, and redaction category hotspots."""
    try:
        result = await asyncio.to_thread(_client.pattern_analysis, days=days)
        return json.dumps(result, ensure_ascii=False, default=str, indent=2)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def session_intel_trends(weeks: int = 4) -> str:
    """Weekly productivity trends for Claude Code usage. Returns per-ISO-week metrics: sessions_count, total_messages, avg_session_length, unique_projects, redactions_count."""
    try:
        result = await asyncio.to_thread(_client.productivity_trends, weeks=weeks)
        return json.dumps(result, ensure_ascii=False, default=str, indent=2)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def session_intel_digest(week_offset: int = 0) -> str:
    """Generate a weekly digest of Claude Code session activity. Includes summary stats, top projects, notable sessions, security report, and comparison vs previous week."""
    try:
        result = await asyncio.to_thread(_client.weekly_digest, week_offset=week_offset)
        return json.dumps(result, ensure_ascii=False, default=str, indent=2)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
async def session_intel_security(days: int = 30) -> str:
    """Security-focused report on sensitive data detection across sessions. Returns total redactions, category breakdown, daily trend, most affected projects, and list of unprocessed sessions."""
    try:
        result = await asyncio.to_thread(_client.security_report, days=days)
        return json.dumps(result, ensure_ascii=False, default=str, indent=2)
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run()

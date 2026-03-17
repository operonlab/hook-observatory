#!/Users/joneshong/.local/bin/python3
"""Session Redactor MCP Server — thin wrapper over SessionRedactorClient SDK.

5 tools:
    session_redactor_status    — aggregate stats (files, redactions, last run)
    session_redactor_sweep     — run full sweep of ~/.claude/projects/
    session_redactor_redact    — redact a single file by path
    session_redactor_patterns  — list all detection patterns
    session_redactor_history   — recent processing records

All logic lives in workshop.clients.session_redactor (SDK layer).

Usage:
    python3 mcp/session-redactor/server.py

Configure in ~/.claude.json:
    "session-redactor": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/session-redactor/server.py"],
        "env": {}
    }
"""

import json
import os
import sys
from asyncio import to_thread

# Allow importing from workshop package regardless of PYTHONPATH
_script_dir = os.path.dirname(os.path.abspath(__file__))
_workshop_libs = os.path.join(_script_dir, "..", "..", "libs", "python", "src")
if os.path.isdir(_workshop_libs) and _workshop_libs not in sys.path:
    sys.path.insert(0, _workshop_libs)

from mcp.server.fastmcp import FastMCP  # noqa: E402
from workshop.clients.session_redactor import SessionRedactorClient  # noqa: E402
from workshop.mcp_helpers import mcp_error_handler  # noqa: E402

mcp = FastMCP("workshop-session-redactor")
client = SessionRedactorClient()


def json_result(data) -> str:
    return json.dumps(data, indent=2, default=str)


# ======================== Tool Handlers ========================


@mcp.tool()
@mcp_error_handler("SessionRedactor")
async def session_redactor_status() -> str:
    """Get Session Redactor aggregate stats: total files processed, total redactions made, and last processing timestamp. Use this to understand how much sensitive data has been cleaned."""
    stats = await to_thread(client.get_stats)
    return json_result(stats)


@mcp.tool()
@mcp_error_handler("SessionRedactor")
async def session_redactor_sweep(trigger: str = "sweep") -> str:
    """Run a full sweep of all Claude session transcripts (~/.claude/projects/). Detects and redacts API keys, passwords, tokens, and other secrets. Returns count of files processed and total redactions made."""
    summary = await to_thread(client.full_sweep, trigger)
    return json_result(summary)


@mcp.tool()
@mcp_error_handler("SessionRedactor")
async def session_redactor_redact(file_path: str, trigger: str = "manual") -> str:
    """Redact sensitive data from a single .jsonl transcript file. Parses JSON, recursively walks all string values, applies all 16 detection patterns (API keys, passwords, tokens, AWS, SSH, etc.), and atomically writes the cleaned file back."""
    result = await to_thread(client.redact_file, file_path, trigger)
    return json_result(result.to_dict())


@mcp.tool()
@mcp_error_handler("SessionRedactor")
async def session_redactor_patterns() -> str:
    """List all sensitive data detection patterns with their names and categories. Categories include: password, api_key, token, aws_key, aws_secret, ssh_key, db_password, generic_secret."""
    patterns = await to_thread(client.list_patterns)
    return json_result(patterns)


@mcp.tool()
@mcp_error_handler("SessionRedactor")
async def session_redactor_history(limit: int = 30, session_id: str = "") -> str:
    """Get recent session transcript processing records. Shows which files were processed, how many redactions were made, and what triggered each processing run."""
    limit = min(limit, 100)  # cap at 100
    if session_id:
        records = await to_thread(client.get_session_history, session_id)
        records = records[:limit]  # SDK has no limit param; truncate here
    else:
        records = await to_thread(client.get_history, limit)
    total_count = len(records)
    return json_result({"total_count": total_count, "records": records})


# ======================== Entry Point ========================

if __name__ == "__main__":
    mcp.run()

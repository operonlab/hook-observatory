#!/usr/bin/env python3
"""Vision MCP Server — Thin wrapper over VisionClient SDK.

Configure in mcpproxy:
    "vision": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/vision/server.py"]
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from sdk_client.vision import VisionClient
from sdk_client.mcp_helpers import json_text, mcp_error_handler

mcp = FastMCP("vision")
client = VisionClient()


@mcp.tool()
@mcp_error_handler("Vision")
async def vision_analyze(
    file_path: str,
    task: str = "describe",
    engine: str = "apple",
    prompt: str | None = None,
) -> str:
    """Analyze image. Tasks: describe, detect, classify, qa, barcode, face."""
    result = await to_thread(
        client.analyze,
        file_path=file_path,
        task=task,
        engine=engine,
        prompt=prompt,
    )
    res = result.get("result", "")
    if isinstance(res, list):
        # Detection/face results
        count = result.get("count", len(res))
        summary = f"**Found**: {count} items\n"
        for item in res[:10]:
            summary += f"- {item}\n"
        return summary

    parts = [
        f"**Result**: {str(res)[:2000]}",
        f"**Engine**: {result.get('engine', '?')}",
        f"**Task**: {result.get('task', '?')}",
    ]
    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("Vision")
async def vision_engines() -> str:
    """List available computer vision engines with supported analysis tasks and capabilities."""
    result = await to_thread(client.list_engines)
    return json_text(result)


if __name__ == "__main__":
    mcp.run()

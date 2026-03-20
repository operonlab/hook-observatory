#!/usr/bin/env python3
"""OCR MCP Server — Thin wrapper over OCRClient SDK.

Usage:
    python3 mcp/ocr/server.py

Configure in mcpproxy:
    "ocr": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/ocr/server.py"]
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients.ocr import OCRClient
from workshop.mcp_helpers import json_text, mcp_error_handler

mcp = FastMCP("ocr")
client = OCRClient()


@mcp.tool()
@mcp_error_handler("OCR")
async def ocr_extract(
    file_path: str,
    languages: str = "zh-Hant,en",
    engine: str = "apple",
) -> str:
    """Extract text from image or PDF. Returns full text and block-level details."""
    lang_list = [l.strip() for l in languages.split(",")]
    result = await to_thread(
        client.extract,
        file_path=file_path,
        languages=lang_list,
        engine=engine,
    )
    text = result.get("text", "")
    blocks = result.get("blocks", [])
    parts = [f"**Text** ({len(text)} chars):\n{text[:3000]}"]
    if len(text) > 3000:
        parts.append(f"... ({len(text) - 3000} chars truncated)")
    parts.append(f"\n**Engine**: {result.get('engine', '?')}")
    parts.append(f"**Blocks**: {len(blocks)}")
    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("OCR")
async def ocr_engines() -> str:
    """List available OCR engines."""
    result = await to_thread(client.list_engines)
    return json_text(result)


if __name__ == "__main__":
    mcp.run()

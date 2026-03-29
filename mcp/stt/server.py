#!/usr/bin/env python3
"""STT MCP Server — Thin wrapper over STTClient SDK.

Usage:
    python3 mcp/stt/server.py

Configure in mcpproxy:
    "stt": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/stt/server.py"]
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from sdk_client.stt import STTClient
from sdk_client.mcp_helpers import json_text, mcp_error_handler

mcp = FastMCP("stt")
client = STTClient()


@mcp.tool()
@mcp_error_handler("STT")
async def stt_transcribe(
    file_path: str,
    language: str = "zh-TW",
    engine: str = "apple",
    operators: str | None = None,
) -> str:
    """Transcribe audio file to text. Returns text, segments, and metadata.

    operators: Comma-separated preprocessors, e.g. "denoise,vad-trim,normalize"
    """
    result = await to_thread(
        client.transcribe,
        file_path=file_path,
        language=language,
        engine=engine,
        operators=operators,
    )
    text = result.get("text", "")
    segments = result.get("segments", [])
    parts = [f"**Text**: {text}", f"**Engine**: {result.get('engine', '?')}"]
    if segments:
        parts.append(f"**Segments**: {len(segments)}")
    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("STT")
async def stt_engines() -> str:
    """List available speech-to-text engines (e.g. Apple, Whisper) with supported languages and capabilities."""
    result = await to_thread(client.list_engines)
    return json_text(result)


@mcp.tool()
@mcp_error_handler("STT")
async def stt_operators() -> str:
    """List available audio preprocessing operators for STT (e.g. denoise, vad-trim, normalize)."""
    result = await to_thread(client.list_operators)
    return json_text(result)


if __name__ == "__main__":
    mcp.run()

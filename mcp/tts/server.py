#!/usr/bin/env python3
"""TTS MCP Server — Thin wrapper over TTSClient SDK.

Usage:
    python3 mcp/tts/server.py

Configure in mcpproxy:
    "tts": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/tts/server.py"]
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from sdk_client.tts import TTSClient
from sdk_client.mcp_helpers import json_text, mcp_error_handler

mcp = FastMCP("tts")
client = TTSClient()


@mcp.tool()
@mcp_error_handler("TTS")
async def tts_synthesize(
    text: str,
    voice: str = "default",
    speed: float = 1.0,
    engine: str = "apple",
) -> str:
    """Synthesize speech from text. Returns audio file path and metadata."""
    result = await to_thread(
        client.synthesize,
        text=text,
        voice=voice,
        speed=speed,
        engine=engine,
    )
    parts = [
        f"**Audio**: {result.get('audio_path', '?')}",
        f"**Duration**: {result.get('duration', 0):.1f}s",
        f"**Engine**: {result.get('engine', '?')}",
    ]
    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("TTS")
async def tts_voices(engine: str = "apple") -> str:
    """List available voices for a TTS engine."""
    result = await to_thread(client.list_voices, engine=engine)
    return json_text(result)


@mcp.tool()
@mcp_error_handler("TTS")
async def tts_engines() -> str:
    """List available text-to-speech engines (e.g. Apple, Edge TTS) with supported languages and capabilities."""
    result = await to_thread(client.list_engines)
    return json_text(result)


if __name__ == "__main__":
    mcp.run()

#!/usr/bin/env python3
"""TTS MCP Server — wrapper over TTSClient SDK (v1 + v2 unified API).

v1 tools (legacy):   tts_synthesize_legacy / tts_voices_legacy / tts_engines_legacy
v2 tools (default):  tts_synthesize / tts_engines / tts_voices /
                     tts_explain_route / tts_healthcheck / tts_lifecycle

Usage:
    python3 mcp/tts/server.py

Configure in mcpproxy (~/.mcpproxy/mcp_config.json):
    "tts": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/tts/server.py"]
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from sdk_client.mcp_helpers import json_text, mcp_error_handler
from sdk_client.tts import TTSClient

mcp = FastMCP("tts")
client = TTSClient()


# =====================================================================
# v2 tools (default, exposes 6 GPU engines with OutputMode + auto-routing)
# =====================================================================


@mcp.tool()
@mcp_error_handler("TTS")
async def tts_synthesize(
    text: str,
    lang: str,
    voice: str = "master",
    engine: str = "auto",
    output: str = "file",
    out_path: str | None = None,
    speed: float = 1.0,
    ref_text: str | None = None,
) -> str:
    """合成語音（v2 API） — auto routing by lang, multi OutputMode.

    Args:
      text:   合成文字（最長 5000）
      lang:   "zh"|"en"|"ja"|"ko"|"auto"
      voice:  voice_id 對應 voices/{voice}.wav（預設 master）
      engine: "auto" 走 lang routing；或填 cosyvoice_v3_vllm / indextts2_base /
              indextts2_jmica / vibevoice / qwen3tts_gpu / cosyvoice_v3_native
      output: "file" 寫 wav → audio_path；"base64" → audio_base64 (推薦 MCP 場景)
      out_path: file mode 可指定（None → server mktemp）
      speed:  0.5–2.0
      ref_text: zero-shot 引擎（qwen3tts_gpu）必填
    """
    es = {"ref_text": ref_text} if ref_text else None
    result = await to_thread(
        client.synthesize_v2,
        text=text, lang=lang, voice=voice, engine=engine,
        output=output, out_path=out_path, speed=speed,
        engine_specific=es,
    )
    return json_text(result)


@mcp.tool()
@mcp_error_handler("TTS")
async def tts_engines() -> str:
    """列 v3 系列 engine（6 個）+ capability + 健康狀態."""
    result = await to_thread(client.list_engines_v2)
    return json_text(result)


@mcp.tool()
@mcp_error_handler("TTS")
async def tts_voices() -> str:
    """列 voices/ 目錄已知 voice."""
    result = await to_thread(client.list_voices_v2)
    return json_text(result)


@mcp.tool()
@mcp_error_handler("TTS")
async def tts_explain_route(
    lang: str, multi_speaker: bool = False, prefer_fast: bool = False
) -> str:
    """顯示 lang 對應 engine + fallback chain."""
    result = await to_thread(
        client.explain_route, lang, multi_speaker=multi_speaker, prefer_fast=prefer_fast
    )
    return json_text(result)


@mcp.tool()
@mcp_error_handler("TTS")
async def tts_healthcheck() -> str:
    """所有 engine 的健康狀態（python/runner 路徑檢查）."""
    result = await to_thread(client.healthz_v2)
    return json_text(result)


@mcp.tool()
@mcp_error_handler("TTS")
async def tts_lifecycle(action: str = "status") -> str:
    """idle engine lifecycle 管理. action: "status" | "sweep"."""
    if action == "sweep":
        result = await to_thread(client.lifecycle_sweep)
    else:
        result = await to_thread(client.lifecycle_status)
    return json_text(result)


# =====================================================================
# v1 tools (legacy, 保留向後相容)
# =====================================================================


@mcp.tool()
@mcp_error_handler("TTS")
async def tts_synthesize_legacy(
    text: str,
    voice: str = "default",
    speed: float = 1.0,
    engine: str = "apple",
) -> str:
    """v1 legacy synthesize — query-params, single output. 新 code 用 tts_synthesize."""
    result = await to_thread(
        client.synthesize, text=text, voice=voice, speed=speed, engine=engine
    )
    parts = [
        f"**Audio**: {result.get('audio_path', '?')}",
        f"**Duration**: {result.get('duration', 0):.1f}s",
        f"**Engine**: {result.get('engine', '?')}",
    ]
    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("TTS")
async def tts_voices_legacy(engine: str = "apple") -> str:
    """v1 legacy voice list — by engine name (Mac engines)."""
    result = await to_thread(client.list_voices, engine=engine)
    return json_text(result)


@mcp.tool()
@mcp_error_handler("TTS")
async def tts_engines_legacy() -> str:
    """v1 legacy engine list — Mac engines (edge/apple/elevenlabs/kokoro/...)."""
    result = await to_thread(client.list_engines)
    return json_text(result)


if __name__ == "__main__":
    mcp.run()

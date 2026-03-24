#!/usr/bin/env python3
"""TPS MCP Server — Thin wrapper over TPSClient SDK.

Usage:
    python3 mcp/tps/server.py

Configure in mcpproxy:
    "tps": {
        "command": "/Users/joneshong/.local/bin/python3",
        "args": ["/Users/joneshong/workshop/mcp/tps/server.py"]
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients.tps import TPSClient
from workshop.mcp_helpers import json_text, mcp_error_handler

mcp = FastMCP("tps")
client = TPSClient()


@mcp.tool()
@mcp_error_handler("TPS")
async def tps_translate(
    text: str,
    target_lang: str = "zh-TW",
    source_lang: str = "auto",
    provider: str | None = None,
) -> str:
    """Translate text using DeepL/Google with caching. Returns translated text + metadata."""
    result = await to_thread(
        client.translate,
        text=text,
        source_lang=source_lang,
        target_lang=target_lang,
        provider=provider,
    )
    cached = " (cached)" if result.get("cached") else ""
    prov = result.get("provider", "?")
    return f"**[{prov}{cached}]** {result['text']}"


@mcp.tool()
@mcp_error_handler("TPS")
async def tps_batch(
    texts: list[str],
    target_lang: str = "zh-TW",
    source_lang: str = "auto",
) -> str:
    """Batch translate multiple texts. Returns all translations."""
    result = await to_thread(
        client.batch_translate,
        texts=texts,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    lines = []
    for r in result.get("results", []):
        cached = " (cached)" if r.get("cached") else ""
        lines.append(f"[{r.get('provider', '?')}{cached}] {r['text']}")
    total = result.get("total_cost_usd", 0)
    lines.append(f"\n**Total**: {len(texts)} texts, ${total:.4f}")
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("TPS")
async def tps_usage() -> str:
    """Show today's translation usage stats and budget."""
    result = await to_thread(client.usage)
    return json_text(result)


if __name__ == "__main__":
    mcp.run()

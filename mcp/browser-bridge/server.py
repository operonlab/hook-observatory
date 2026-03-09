#!/usr/bin/env python3
"""Browser-Bridge MCP Server — AI browser session management thin adapter.

5 tools: bridge_chat, bridge_new, bridge_history, bridge_sessions, bridge_providers
Uses workshop.clients.browser_bridge SDK.

Usage:
    python3 mcp/browser-bridge/server.py
"""

import json
from asyncio import to_thread

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.browser_bridge import BrowserBridgeClient

server = Server("workshop-browser-bridge")
client = BrowserBridgeClient()


# ======================== Helpers ========================


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def json_result(data) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="bridge_chat",
            description="向指定瀏覽器 session 發送訊息並取得 AI 回應",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                    "message": {"type": "string", "description": "發送的訊息"},
                    "provider": {"type": "string", "description": "AI 提供者（可選，使用 session 預設）"},
                },
                "required": ["session_id", "message"],
            },
        ),
        Tool(
            name="bridge_new",
            description="建立新的瀏覽器 AI session",
            inputSchema={
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "AI 提供者（如 chatgpt, claude, gemini）"},
                    "title": {"type": "string", "description": "Session 標題"},
                },
                "required": ["provider"],
            },
        ),
        Tool(
            name="bridge_history",
            description="取得指定 session 的對話歷史",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID"},
                    "limit": {"type": "integer", "default": 20, "description": "最多回傳筆數"},
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="bridge_sessions",
            description="列出所有瀏覽器 AI sessions",
            inputSchema={
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "篩選特定提供者"},
                    "active_only": {"type": "boolean", "default": False, "description": "只顯示活躍 sessions"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="bridge_providers",
            description="列出可用的 AI 提供者及其狀態",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


# ======================== Tool Handlers ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    try:
        if name == "bridge_chat":
            result = await to_thread(
                client.chat,
                session_id=arguments["session_id"],
                message=arguments["message"],
                provider=arguments.get("provider"),
            )
            return json_result(result)

        elif name == "bridge_new":
            result = await to_thread(
                client.new_session,
                provider=arguments["provider"],
                title=arguments.get("title"),
            )
            return json_result(result)

        elif name == "bridge_history":
            result = await to_thread(
                client.get_history,
                session_id=arguments["session_id"],
                limit=arguments.get("limit", 20),
            )
            return json_result(result)

        elif name == "bridge_sessions":
            result = await to_thread(
                client.list_sessions,
                provider=arguments.get("provider"),
                active_only=arguments.get("active_only", False),
                limit=arguments.get("limit", 20),
            )
            return json_result(result)

        elif name == "bridge_providers":
            result = await to_thread(client.list_providers)
            return json_result(result)

        else:
            return text_result(f"Unknown tool: {name}")

    except APIConnectionError as e:
        return text_result(f"連線錯誤: {e}")
    except APIError as e:
        return text_result(f"API 錯誤 [{e.status_code}]: {e}")
    except Exception as e:
        return text_result(f"錯誤: {e}")


# ======================== Entrypoint ========================

if __name__ == "__main__":
    import asyncio

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(main())

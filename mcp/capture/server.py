#!/usr/bin/env python3
"""Capture MCP Server — progressive data enrichment for all modules.

10 tools: capture (create), capture_list, capture_update, capture_promote, capture_stats,
capture_delete, capture_batch_promote, capture_batch_fill, capture_enrichments, capture_enrich.
Uses workshop.clients.capture SDK.

Usage:
    python3 mcp/capture/server.py

Configure in ~/.claude.json:
    "workshop-capture": {
        "command": "python3",
        "args": ["/path/to/workshop/mcp/capture/server.py"],
        "env": {
            "CORE_API_URL": "http://localhost:8801",
            "CAPTURE_SPACE_ID": "default"
        }
    }
"""

import asyncio
import json
from asyncio import to_thread

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.capture import CaptureClient

server = Server("workshop-capture")
client = CaptureClient()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="capture_create",
            description="快速捕捉資料（不需填寫所有必填欄位，系統自動填入 smart defaults）。支援 finance/transaction、finance/subscription、finance/installment。",
            inputSchema={
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "description": "目標模組（如 finance, invest）",
                    },
                    "entity_type": {
                        "type": "string",
                        "description": "實體類型（如 transaction, subscription, installment）",
                    },
                    "payload": {
                        "type": "object",
                        "description": "資料欄位（只需填已知的，其餘自動填入）",
                    },
                    "raw_input": {
                        "type": "string",
                        "description": "原始自然語言輸入（供日後 AI 解析）",
                    },
                },
                "required": ["module", "entity_type", "payload"],
            },
        ),
        Tool(
            name="capture_list",
            description="列出捕捉中的資料（可依模組、類型、狀態篩選）",
            inputSchema={
                "type": "object",
                "properties": {
                    "module": {"type": "string", "description": "篩選模組"},
                    "entity_type": {"type": "string", "description": "篩選實體類型"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "promoted", "expired"],
                        "description": "篩選狀態",
                    },
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="capture_update",
            description="補充捕捉資料的欄位（progressive enrichment）",
            inputSchema={
                "type": "object",
                "properties": {
                    "capture_id": {"type": "string", "description": "捕捉 ID"},
                    "payload": {
                        "type": "object",
                        "description": "要補充/覆蓋的欄位",
                    },
                },
                "required": ["capture_id", "payload"],
            },
        ),
        Tool(
            name="capture_promote",
            description="將捕捉資料晉升為正式記錄（需欄位足夠完整）",
            inputSchema={
                "type": "object",
                "properties": {
                    "capture_id": {"type": "string", "description": "捕捉 ID"},
                },
                "required": ["capture_id"],
            },
        ),
        Tool(
            name="capture_stats",
            description="取得捕捉資料統計（數量、模組分布、狀態分布）",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="capture_delete",
            description="刪除捕捉資料",
            inputSchema={
                "type": "object",
                "properties": {
                    "capture_id": {"type": "string", "description": "捕捉 ID"},
                },
                "required": ["capture_id"],
            },
        ),
        Tool(
            name="capture_batch_promote",
            description="批次晉升多筆捕捉資料為正式記錄",
            inputSchema={
                "type": "object",
                "properties": {
                    "capture_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要晉升的捕捉 ID 列表",
                    },
                },
                "required": ["capture_ids"],
            },
        ),
        Tool(
            name="capture_batch_fill",
            description="批次將相同欄位填入多筆捕捉資料（progressive enrichment）",
            inputSchema={
                "type": "object",
                "properties": {
                    "capture_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要更新的捕捉 ID 列表",
                    },
                    "payload": {
                        "type": "object",
                        "description": "要填入的欄位（所有指定捕捉皆會套用）",
                    },
                },
                "required": ["capture_ids", "payload"],
            },
        ),
        Tool(
            name="capture_enrichments",
            description="取得捕捉資料的 enrichment 歷史紀錄（哪個 agent 在何時填入哪些欄位）",
            inputSchema={
                "type": "object",
                "properties": {
                    "capture_id": {"type": "string", "description": "捕捉 ID"},
                },
                "required": ["capture_id"],
            },
        ),
        Tool(
            name="capture_enrich",
            description="觸發 LLM 豐富（Haiku 解析 raw_input 填補缺失欄位）",
            inputSchema={
                "type": "object",
                "properties": {
                    "capture_id": {"type": "string", "description": "Capture ID"},
                },
                "required": ["capture_id"],
            },
        ),
    ]


# ======================== Tool Handlers ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "capture_create":
            result = await to_thread(
                client.create,
                module=arguments["module"],
                entity_type=arguments["entity_type"],
                payload=arguments["payload"],
                raw_input=arguments.get("raw_input"),
            )
            completeness = int(result.get("completeness", 0) * 100)
            missing = result.get("missing_fields", [])
            lines = [
                f"Captured! ID: {result['id']}",
                f"Completeness: {completeness}%",
                f"Status: {result['status']}",
            ]
            if missing:
                lines.append(f"Missing: {', '.join(missing)}")
            if result.get("expires_at"):
                lines.append(f"Expires: {result['expires_at'][:10]}")
            return text_result("\n".join(lines))

        elif name == "capture_list":
            items = await to_thread(
                client.list,
                module=arguments.get("module"),
                entity_type=arguments.get("entity_type"),
                status=arguments.get("status"),
                limit=arguments.get("limit", 20),
            )
            if not items:
                return text_result("No captures found.")
            lines = []
            for c in items:
                pct = int(c.get("completeness", 0) * 100)
                desc = c.get("payload", {}).get("description", c.get("raw_input", ""))
                if desc and len(desc) > 40:
                    desc = desc[:37] + "..."
                lines.append(
                    f"- [{c['module']}/{c['entity_type']}] {desc or '(no desc)'} "
                    f"| {pct}% | {c['status']} | {c['id'][:12]}..."
                )
            return text_result(f"{len(items)} captures:\n" + "\n".join(lines))

        elif name == "capture_update":
            result = await to_thread(
                client.update,
                capture_id=arguments["capture_id"],
                payload=arguments["payload"],
            )
            completeness = int(result.get("completeness", 0) * 100)
            missing = result.get("missing_fields", [])
            lines = [f"Updated! Completeness: {completeness}%"]
            if missing:
                lines.append(f"Still missing: {', '.join(missing)}")
            else:
                lines.append("All fields complete — ready to promote!")
            return text_result("\n".join(lines))

        elif name == "capture_promote":
            result = await to_thread(client.promote, capture_id=arguments["capture_id"])
            if result.get("success"):
                return text_result(f"Promoted! New record ID: {result['promoted_id']}")
            else:
                missing = result.get("missing_fields", [])
                error = result.get("error", "Unknown error")
                lines = ["Promote failed."]
                if missing:
                    lines.append(f"Missing fields: {', '.join(missing)}")
                lines.append(f"Error: {error}")
                return text_result("\n".join(lines))

        elif name == "capture_stats":
            result = await to_thread(client.stats)
            lines = [f"Total captures: {result['total']}"]
            if result.get("by_module"):
                lines.append("By module: " + json.dumps(result["by_module"]))
            if result.get("by_status"):
                lines.append("By status: " + json.dumps(result["by_status"]))
            return text_result("\n".join(lines))

        elif name == "capture_delete":
            await to_thread(client.delete, capture_id=arguments["capture_id"])
            return text_result("Capture deleted.")

        elif name == "capture_batch_promote":
            results = await to_thread(client.batch_promote, capture_ids=arguments["capture_ids"])
            lines = [f"Batch promote: {len(results)} results"]
            for r in results:
                cid = r.get("capture_id", r.get("id", "?"))[:12]
                if r.get("success"):
                    lines.append(f"  {cid}...  promoted -> {r.get('promoted_id', '?')[:12]}...")
                else:
                    missing = ", ".join(r.get("missing_fields", []))
                    error = r.get("error", "failed")
                    detail = f" (missing: {missing})" if missing else ""
                    lines.append(f"  {cid}...  FAILED  {error}{detail}")
            return text_result("\n".join(lines))

        elif name == "capture_batch_fill":
            results = await to_thread(
                client.batch_fill,
                capture_ids=arguments["capture_ids"],
                payload=arguments["payload"],
            )
            lines = [f"Batch fill: {len(results)} updated"]
            for r in results:
                cid = r.get("id", "?")[:12]
                pct = int(r.get("completeness", 0) * 100)
                missing = r.get("missing_fields", [])
                status_str = "complete" if not missing else f"missing: {', '.join(missing)}"
                lines.append(f"  {cid}...  {pct}%  {status_str}")
            return text_result("\n".join(lines))

        elif name == "capture_enrich":
            result = await to_thread(client.enrich, arguments["capture_id"])
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "capture_enrichments":
            history = await to_thread(client.enrichments, capture_id=arguments["capture_id"])
            if not history:
                return text_result("No enrichment history found.")
            lines = [f"Enrichment history ({len(history)} entries):"]
            for entry in history:
                agent = entry.get("agent_id", "unknown")
                ts = str(entry.get("created_at", entry.get("timestamp", "")))[:19]
                delta = entry.get("delta", {})
                delta_str = (
                    ", ".join(f"{k}={v}" for k, v in delta.items()) if delta else "(no fields)"
                )
                lines.append(f"  {ts}  {agent}  {delta_str}")
            return text_result("\n".join(lines))

        else:
            return text_result(f"Unknown tool: {name}")

    except APIConnectionError as e:
        return text_result(f"Connection error: {e}")
    except APIError as e:
        return text_result(f"API error ({e.status_code}): {e.detail}")
    except Exception as e:
        return text_result(f"Unexpected error: {type(e).__name__}: {e}")


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

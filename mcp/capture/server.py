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

import json
from asyncio import to_thread

from mcp.server.fastmcp import FastMCP
from workshop.clients.capture import CaptureClient
from workshop.mcp_helpers import json_text, mcp_error_handler

mcp = FastMCP("workshop-capture")
client = CaptureClient()


# ======================== Tool Handlers ========================


@mcp.tool()
@mcp_error_handler("Capture")
async def capture_create(
    module: str,
    entity_type: str,
    payload: str,
    raw_input: str = "",
) -> str:
    """快速捕捉資料（不需填寫所有必填欄位，系統自動填入 smart defaults）。支援 finance/transaction、finance/subscription、finance/installment。payload 為 JSON 字串。"""
    payload_dict = json.loads(payload) if isinstance(payload, str) else payload
    result = await to_thread(
        client.create,
        module=module,
        entity_type=entity_type,
        payload=payload_dict,
        raw_input=raw_input or None,
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
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Capture")
async def capture_list(
    module: str = "",
    entity_type: str = "",
    status: str = "",
    limit: int = 20,
) -> str:
    """列出捕捉中的資料（可依模組、類型、狀態篩選）。status 可為 pending/promoted/expired。"""
    raw = await to_thread(
        client.list,
        module=module or None,
        entity_type=entity_type or None,
        status=status or None,
        limit=limit,
    )
    items = raw.get("items", []) if isinstance(raw, dict) else raw
    if not items:
        return "No captures found."
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
    total = raw.get("total", len(items)) if isinstance(raw, dict) else len(items)
    return f"{len(items)} captures (total: {total}):\n" + "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Capture")
async def capture_update(capture_id: str, payload: str) -> str:
    """補充捕捉資料的欄位（progressive enrichment）。payload 為 JSON 字串。"""
    payload_dict = json.loads(payload) if isinstance(payload, str) else payload
    result = await to_thread(
        client.update,
        capture_id=capture_id,
        payload=payload_dict,
    )
    completeness = int(result.get("completeness", 0) * 100)
    missing = result.get("missing_fields", [])
    lines = [f"Updated! Completeness: {completeness}%"]
    if missing:
        lines.append(f"Still missing: {', '.join(missing)}")
    else:
        lines.append("All fields complete — ready to promote!")
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Capture")
async def capture_promote(capture_id: str) -> str:
    """將捕捉資料晉升為正式記錄（需欄位足夠完整）。"""
    result = await to_thread(client.promote, capture_id=capture_id)
    if result.get("success"):
        return f"Promoted! New record ID: {result['promoted_id']}"
    else:
        missing = result.get("missing_fields", [])
        error = result.get("error", "Unknown error")
        lines = ["Promote failed."]
        if missing:
            lines.append(f"Missing fields: {', '.join(missing)}")
        lines.append(f"Error: {error}")
        return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Capture")
async def capture_stats() -> str:
    """取得捕捉資料統計（數量、模組分布、狀態分布）。"""
    result = await to_thread(client.stats)
    lines = [f"Total captures: {result['total']}"]
    if result.get("by_module"):
        lines.append("By module: " + json.dumps(result["by_module"]))
    if result.get("by_status"):
        lines.append("By status: " + json.dumps(result["by_status"]))
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Capture")
async def capture_delete(capture_id: str) -> str:
    """刪除捕捉資料。"""
    await to_thread(client.delete, capture_id=capture_id)
    return "Capture deleted."


@mcp.tool()
@mcp_error_handler("Capture")
async def capture_batch_promote(capture_ids: str) -> str:
    """批次晉升多筆捕捉資料為正式記錄。capture_ids 為逗號分隔的 ID 字串。"""
    ids = [cid.strip() for cid in capture_ids.split(",") if cid.strip()]
    results = await to_thread(client.batch_promote, capture_ids=ids)
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
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Capture")
async def capture_batch_fill(capture_ids: str, payload: str) -> str:
    """批次將相同欄位填入多筆捕捉資料（progressive enrichment）。capture_ids 為逗號分隔的 ID 字串，payload 為 JSON 字串。"""
    ids = [cid.strip() for cid in capture_ids.split(",") if cid.strip()]
    payload_dict = json.loads(payload) if isinstance(payload, str) else payload
    results = await to_thread(
        client.batch_fill,
        capture_ids=ids,
        payload=payload_dict,
    )
    lines = [f"Batch fill: {len(results)} updated"]
    for r in results:
        cid = r.get("id", "?")[:12]
        pct = int(r.get("completeness", 0) * 100)
        missing = r.get("missing_fields", [])
        status_str = "complete" if not missing else f"missing: {', '.join(missing)}"
        lines.append(f"  {cid}...  {pct}%  {status_str}")
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Capture")
async def capture_enrichments(capture_id: str) -> str:
    """取得捕捉資料的 enrichment 歷史紀錄（哪個 agent 在何時填入哪些欄位）。"""
    history = await to_thread(client.enrichments, capture_id=capture_id)
    if not history:
        return "No enrichment history found."
    lines = [f"Enrichment history ({len(history)} entries):"]
    for entry in history:
        agent = entry.get("agent_id", "unknown")
        ts = str(entry.get("created_at", entry.get("timestamp", "")))[:19]
        delta = entry.get("delta", {})
        delta_str = ", ".join(f"{k}={v}" for k, v in delta.items()) if delta else "(no fields)"
        lines.append(f"  {ts}  {agent}  {delta_str}")
    return "\n".join(lines)


@mcp.tool()
@mcp_error_handler("Capture")
async def capture_enrich(capture_id: str) -> str:
    """觸發 LLM 豐富（Haiku 解析 raw_input 填補缺失欄位）。"""
    result = await to_thread(client.enrich, capture_id)
    return json_text(result)


if __name__ == "__main__":
    mcp.run()

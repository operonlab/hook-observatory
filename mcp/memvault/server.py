#!/usr/bin/env python3
"""Memvault MCP Server — Slim adapter — 8 tools + 2 resources. Uses workshop.clients.memvault SDK.

Usage:
    python3 mcp/memvault/server.py

Configure in ~/.claude.json:
    "memvault": {
        "command": "python3",
        "args": ["/path/to/workshop/mcp/memvault/server.py"],
        "env": {
            "CORE_API_URL": "http://localhost:8801",
            "MEMVAULT_SPACE_ID": "default"
        }
    }
"""

from asyncio import to_thread
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.memvault import MemvaultClient

server = Server("memvault")
client = MemvaultClient()


# ======================== Helpers ========================


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="memvault_recall",
            description="根據 query 搜尋相關記憶（keyword + semantic hybrid search with RRF）。mode='cascade' 啟用四層 Cascade Recall",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜尋查詢"},
                    "max_results": {"type": "integer", "default": 5},
                    "min_score": {"type": "number", "default": 0.3},
                    "mode": {
                        "type": "string",
                        "enum": ["default", "cascade"],
                        "default": "default",
                        "description": "cascade = 四層 KG Cascade Recall",
                    },
                    "since": {
                        "type": "string",
                        "description": "Filter: created_at >= date (ISO, e.g. 2026-03-01)",
                    },
                    "before": {
                        "type": "string",
                        "description": "Filter: created_at <= date (ISO, e.g. 2026-03-11)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="memvault_extract",
            description="從 session transcript 提煉記憶並存入 memvault",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_session": {"type": "string"},
                    "content": {"type": "string", "description": "提煉後的記憶內容"},
                    "block_type": {
                        "type": "string",
                        "enum": ["knowledge", "skill", "attitude", "general"],
                        "default": "general",
                    },
                    "tags": {"type": "array", "items": {"type": "string"}, "default": []},
                },
                "required": ["content"],
            },
        ),
        Tool(
            name="memvault_profile",
            description="查看或重建 KAS Profile（Knowledge/Attitude/Skills 三維量化）",
            inputSchema={
                "type": "object",
                "properties": {
                    "rebuild": {"type": "boolean", "default": False},
                },
            },
        ),
        Tool(
            name="memvault_kg_wisdom",
            description="查詢 Wisdom nodes（跨 cluster 提煉的高層洞見）",
            inputSchema={
                "type": "object",
                "properties": {
                    "confidence": {
                        "type": "string",
                        "enum": ["HIGH", "MEDIUM", "LOW"],
                        "description": "篩選 confidence 等級",
                    },
                    "tag": {"type": "string", "description": "篩選 tag"},
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "回傳筆數上限",
                    },
                },
            },
        ),
        Tool(
            name="memvault_kg_cascade_recall",
            description="四層 Cascade Recall：L2 Wisdom → L1 Clusters → L0 Triples → Blocks",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜尋查詢"},
                    "top_k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="memvault_attitude_current",
            description="查詢當前有效的態度事實（attitude facts，非 superseded）",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "篩選態度類別"},
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "回傳筆數上限",
                    },
                },
            },
        ),
        Tool(
            name="memvault_attitude_evolve",
            description="態度演化：輸入新 fact，系統判斷 ADD / UPDATE / NOOP（Mem0 pattern）",
            inputSchema={
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "description": "態度事實內容"},
                    "category": {"type": "string", "description": "態度類別"},
                    "source_session": {"type": "string", "description": "來源 session ID"},
                },
                "required": ["fact", "category"],
            },
        ),
        Tool(
            name="memvault_skill_proficiency",
            description="查詢 Skill 熟練度排行（按 proficiency score 降序）",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 20,
                        "description": "回傳筆數上限",
                    },
                },
            },
        ),
        Tool(
            name="memvault_kg_invalidate",
            description="標記 triple 為無效（軟性時間失效），用於矛盾偵測或手動修正",
            inputSchema={
                "type": "object",
                "properties": {
                    "triple_id": {"type": "string", "description": "要失效的 Triple ID"},
                    "reason": {
                        "type": "string",
                        "default": "manual",
                        "description": "失效原因 (contradiction / manual / correction)",
                    },
                    "replacement_triple_id": {
                        "type": "string",
                        "description": "取代此 triple 的新 triple ID",
                    },
                },
                "required": ["triple_id"],
            },
        ),
        Tool(
            name="memvault_kg_traverse",
            description="從種子實體出發的多跳圖遍歷（遞迴 CTE），支援方向過濾、predicate 過濾",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "種子實體名稱"},
                    "max_depth": {
                        "type": "integer",
                        "default": 2,
                        "description": "最大遍歷深度 (1-4)",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["outgoing", "incoming", "both"],
                        "default": "both",
                    },
                    "predicates": {
                        "type": "string",
                        "description": "逗號分隔的 predicate 過濾",
                    },
                    "max_results": {"type": "integer", "default": 200},
                },
                "required": ["entity"],
            },
        ),
        Tool(
            name="memvault_entity_stats",
            description="實體解析統計：canonical 總數、aliases 總數、平均合併次數、未解析 triples",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="memvault_entity_merge",
            description="合併兩個 canonical entity（secondary → primary），自動更新所有引用的 triples",
            inputSchema={
                "type": "object",
                "properties": {
                    "primary_id": {"type": "string", "description": "保留的主要 entity ID"},
                    "secondary_id": {"type": "string", "description": "被合併的次要 entity ID"},
                },
                "required": ["primary_id", "secondary_id"],
            },
        ),
        Tool(
            name="memvault_session_context",
            description="查詢某 session 的完整上下文：blocks + triples + entities（Flywheel cross-reference）",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_session": {
                        "type": "string",
                        "description": "來源 session ID",
                    },
                    "space_id": {
                        "type": "string",
                        "default": "default",
                        "description": "Space ID",
                    },
                },
                "required": ["source_session"],
            },
        ),
        Tool(
            name="memvault_intelligence_ingest",
            description="將 intelligence digest 注入 memvault（觸發 DIGEST_COMPLETED 事件 → 自動建立 knowledge block + KG triples）",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Digest 內容（至少 10 字元）",
                    },
                    "space_id": {
                        "type": "string",
                        "default": "default",
                    },
                    "digest_type": {
                        "type": "string",
                        "enum": ["daily", "weekly"],
                        "default": "weekly",
                    },
                    "period": {
                        "type": "string",
                        "default": "",
                        "description": "期間標籤，如 '2026-W11'",
                    },
                },
                "required": ["content"],
            },
        ),
    ]


# ======================== Tool Handlers ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        match name:
            case "memvault_recall":
                return await handle_recall(arguments)
            case "memvault_extract":
                return await handle_extract(arguments)
            case "memvault_profile":
                return await handle_profile(arguments)
            case "memvault_kg_wisdom":
                return await handle_kg_wisdom(arguments)
            case "memvault_kg_cascade_recall":
                return await handle_kg_cascade_recall(arguments)
            case "memvault_attitude_current":
                return await handle_attitude_current(arguments)
            case "memvault_attitude_evolve":
                return await handle_attitude_evolve(arguments)
            case "memvault_skill_proficiency":
                return await handle_skill_proficiency(arguments)
            case "memvault_kg_invalidate":
                return await handle_kg_invalidate(arguments)
            case "memvault_kg_traverse":
                return await handle_kg_traverse(arguments)
            case "memvault_entity_stats":
                return await handle_entity_stats(arguments)
            case "memvault_entity_merge":
                return await handle_entity_merge(arguments)
            case "memvault_session_context":
                return await handle_session_context(arguments)
            case "memvault_intelligence_ingest":
                return await handle_intelligence_ingest(arguments)
            case _:
                return text_result(f"Unknown tool: {name}")
    except APIError as e:
        return text_result(f"memvault error: {type(e).__name__}: {e}")
    except APIConnectionError as e:
        return text_result(f"memvault error: {type(e).__name__}: {e}")
    except Exception as e:
        return text_result(f"Unexpected error: {type(e).__name__}: {e}")


# ======================== Tool Implementations ========================


async def handle_recall(args: dict) -> list[TextContent]:
    """memvault_recall -- semantic search, or cascade recall when mode='cascade'."""
    query = args["query"]
    max_results = args.get("max_results", 5)
    mode = args.get("mode", "default")

    if mode == "cascade":
        return await handle_kg_cascade_recall({"query": query, "top_k": max_results})

    raw = await to_thread(
        client.recall,
        query,
        top_k=max_results,
        min_score=args.get("min_score", 0.3),
        date_from=args.get("since"),
        date_to=args.get("before"),
    )
    results = raw.get("results", []) if isinstance(raw, dict) else raw

    if results:
        blocks_text = "\n\n---\n\n".join(
            f"**[Score {r['score']}]** ({r['block']['block_type']})\n"
            f"Tags: {', '.join(r['block'].get('tags', []))}\n"
            f"{r['block']['content'][:300]}..."
            for r in results
        )
        return text_result(f"Found {len(results)} memories (semantic search)\n\n{blocks_text}")

    return text_result(f"No matching memories found for: {query}")


async def handle_extract(args: dict) -> list[TextContent]:
    """memvault_extract -- create a new memory block."""
    result = await to_thread(
        client.extract,
        content=args["content"],
        block_type=args.get("block_type", "general"),
        tags=args.get("tags", []),
        source_session=args.get("source_session"),
    )
    return text_result(
        f"Memory extracted and stored.\n"
        f"Block ID: {result['id']}\n"
        f"Type: {result['block_type']}\n"
        f"Tags: {', '.join(result.get('tags', []))}"
    )


async def handle_profile(args: dict) -> list[TextContent]:
    """memvault_profile -- KAS profile scores."""
    profile = await to_thread(client.profile, rebuild=args.get("rebuild", False))
    return text_result(
        f"# KAS Profile\n\n"
        f"- Knowledge: {profile.get('knowledge_score', 0)}\n"
        f"- Attitude: {profile.get('attitude_score', 0)}\n"
        f"- Skill: {profile.get('skill_score', 0)}\n"
        f"- Updated: {profile.get('updated_at', 'N/A')}"
    )


async def handle_kg_wisdom(args: dict) -> list[TextContent]:
    """memvault_kg_wisdom -- list wisdom nodes."""
    result = await to_thread(client.wisdom, confidence=args.get("confidence"), tag=args.get("tag"))
    if not result:
        return text_result("No wisdom nodes found.")

    total = len(result)
    limit = args.get("limit", 20)
    items = result[:limit]

    wisdom_text = "\n\n---\n\n".join(
        f"**[{w['confidence']}]** {w['wisdom']}\n"
        f"Bridge: {w['bridge_entity']} | Evidence: {w.get('evidence_count', '?')}"
        + (f"\nTags: {', '.join(w.get('tags', []))}" if w.get("tags") else "")
        for w in items
    )
    truncated = f" (showing {limit} of {total})" if total > limit else ""
    return text_result(f"# Wisdom Nodes ({total} total{truncated})\n\n{wisdom_text}")


async def handle_kg_cascade_recall(args: dict) -> list[TextContent]:
    """memvault_kg_cascade_recall -- four-layer cascade recall."""
    query = args["query"]
    top_k = args.get("top_k", 5)

    result = await to_thread(client.cascade, query, top_k=top_k)
    layers = result.get("layers_searched", [])

    parts: list[str] = [
        f'# Cascade Recall: "{query}"',
        f"Layers searched: {', '.join(layers) or 'none'}",
        "",
    ]

    wisdom = result.get("wisdom", [])
    if wisdom:
        parts.append(f"## L2 Wisdom ({len(wisdom)})")
        for w in wisdom:
            parts.append(f"  [{w['confidence']}] {w['wisdom']}")
        parts.append("")

    clusters = result.get("clusters", [])
    if clusters:
        parts.append(f"## L1 Clusters ({len(clusters)})")
        for c in clusters:
            parts.append(f"  {c['name']} (size: {c['size']})")
        parts.append("")

    triples = result.get("triples", [])
    if triples:
        parts.append(f"## L0 Triples ({len(triples)})")
        for t in triples:
            parts.append(f"  {t['subject']} --[{t['predicate']}]--> {t['object']}")
        parts.append("")

    blocks = result.get("blocks", [])
    if blocks:
        parts.append(f"## Memory Blocks ({len(blocks)})")
        for b in blocks:
            content = b.get("content", "")[:200]
            parts.append(f"  [{b.get('block_type', '?')}] {content}...")
        parts.append("")

    if not (wisdom or clusters or triples or blocks):
        parts.append("No results found across all layers.")

    return text_result("\n".join(parts))


async def handle_attitude_current(args: dict) -> list[TextContent]:
    """memvault_attitude_current -- list active attitude facts."""
    result = await to_thread(client.attitudes, category=args.get("category"))
    if not result:
        return text_result("No active attitude facts found.")

    total = len(result)
    limit = args.get("limit", 20)
    items = result[:limit]

    facts_text = "\n\n---\n\n".join(
        f"**[{a['category']}]** {a['fact']}\n"
        f"Confidence: {a.get('confidence', 0.5):.2f} | Operation: {a.get('operation', 'ADD')}"
        for a in items
    )
    truncated = f" (showing {limit} of {total})" if total > limit else ""
    return text_result(f"# Current Attitudes ({total} active{truncated})\n\n{facts_text}")


async def handle_attitude_evolve(args: dict) -> list[TextContent]:
    """memvault_attitude_evolve -- evolve an attitude fact."""
    result = await to_thread(
        client.attitude_evolve,
        fact=args["fact"],
        category=args["category"],
        source_session=args.get("source_session"),
    )
    operation = result.get("operation", "?")
    fact_id = result.get("fact_id", "?")
    message = result.get("message", "")
    previous_id = result.get("previous_id")

    lines = [
        f"Attitude evolve: **{operation}**",
        f"Fact ID: {fact_id}",
        f"Message: {message}",
    ]
    if previous_id:
        lines.append(f"Supersedes: {previous_id}")

    return text_result("\n".join(lines))


async def handle_skill_proficiency(args: dict) -> list[TextContent]:
    """memvault_skill_proficiency -- skill proficiency ranking."""
    result = await to_thread(client.skill_proficiency)
    if not result:
        return text_result("No skill proficiency data found.")

    total = len(result)
    limit = args.get("limit", 20)
    items = result[:limit]

    rows = "\n".join(
        f"  {i + 1:2d}. {p['skill_name']:<40s} "
        f"proficiency={p.get('proficiency', 0):.2f}  "
        f"invocations={p.get('invocation_count', 0)}  "
        f"success_rate={p.get('success_rate', 0):.0%}"
        for i, p in enumerate(items)
    )
    truncated = f" (showing {limit} of {total})" if total > limit else ""
    return text_result(f"# Skill Proficiency Ranking ({total} skills{truncated})\n\n{rows}")


async def handle_kg_invalidate(args: dict) -> list[TextContent]:
    """memvault_kg_invalidate -- invalidate a triple."""
    result = await to_thread(
        client.invalidate_triple,
        args["triple_id"],
        reason=args.get("reason", "manual"),
        replacement_id=args.get("replacement_triple_id"),
    )
    return text_result(
        f"Triple invalidated.\n"
        f"ID: {result.get('id', '?')}\n"
        f"Subject: {result.get('subject', '?')} → Object: {result.get('object', '?')}\n"
        f"Reason: {result.get('invalidation_reason', 'manual')}"
    )


async def handle_kg_traverse(args: dict) -> list[TextContent]:
    """memvault_kg_traverse -- multi-hop graph traversal."""
    result = await to_thread(
        client.graph_traverse,
        entity=args["entity"],
        max_depth=args.get("max_depth", 2),
        direction=args.get("direction", "both"),
        predicates=args.get("predicates"),
        max_results=args.get("max_results", 200),
    )
    nodes = result.get("nodes", [])
    edges = result.get("edges", [])
    truncated = result.get("truncated", False)

    parts = [
        f"# Graph Traversal: {result.get('seed_entity', '?')}",
        f"Direction: {result.get('direction', '?')} | Max depth: {result.get('max_depth', '?')}",
        f"Nodes: {len(nodes)} | Edges: {len(edges)}{' (TRUNCATED)' if truncated else ''}",
        "",
    ]
    for edge in edges[:30]:
        d = edge.get("depth", "?")
        parts.append(f"[d={d}] {edge['source']} --[{edge['predicate']}]--> {edge['target']}")
    if len(edges) > 30:
        parts.append(f"... and {len(edges) - 30} more edges")

    return text_result("\n".join(parts))


async def handle_entity_stats(args: dict) -> list[TextContent]:
    """memvault_entity_stats -- entity resolution statistics."""
    result = await to_thread(client.entity_stats)
    return text_result(
        f"# Entity Resolution Stats\n\n"
        f"- Total entities: {result.get('total_entities', 0)}\n"
        f"- Total aliases: {result.get('total_aliases', 0)}\n"
        f"- Avg merge count: {result.get('avg_merge_count', 1.0):.2f}\n"
        f"- Unresolved triples: {result.get('unresolved_triples', 0)}"
    )


async def handle_entity_merge(args: dict) -> list[TextContent]:
    """memvault_entity_merge -- merge two entities."""
    result = await to_thread(
        client.merge_entities,
        args["primary_id"],
        args["secondary_id"],
    )
    return text_result(
        f"Entity merge complete.\n"
        f"Canonical: {result.get('canonical_name', '?')}\n"
        f"Aliases: {', '.join(result.get('aliases', []))}\n"
        f"Triples updated: {result.get('triples_updated', 0)}"
    )


async def handle_session_context(args: dict) -> list[TextContent]:
    """memvault_session_context -- blocks + triples + entities for a session."""
    result = await to_thread(
        client.session_context,
        args["source_session"],
        space_id=args.get("space_id", "default"),
    )
    summary = result.get("summary", {})
    parts = [
        f"# Session Context: {result.get('source_session', '?')}",
        f"Blocks: {summary.get('total_blocks', 0)} | "
        f"Triples: {summary.get('total_triples', 0)} | "
        f"Entities: {summary.get('total_entities', 0)}",
        "",
    ]

    blocks = result.get("blocks", [])
    if blocks:
        parts.append(f"## Blocks ({len(blocks)})")
        for b in blocks:
            content = b.get("content", "")[:150]
            parts.append(f"  [{b.get('block_type', '?')}] {content}...")
        parts.append("")

    triples = result.get("triples", [])
    if triples:
        parts.append(f"## Triples ({len(triples)})")
        for t in triples[:20]:
            parts.append(f"  {t['subject']} --[{t['predicate']}]--> {t['object']}")
        if len(triples) > 20:
            parts.append(f"  ... and {len(triples) - 20} more")
        parts.append("")

    entities = result.get("entities", [])
    if entities:
        parts.append(f"## Entities ({len(entities)})")
        for e in entities:
            aliases = ", ".join(e.get("aliases", []))
            parts.append(
                f"  {e['canonical_name']} ({e.get('entity_type', '?')})"
                + (f" aliases: {aliases}" if aliases else "")
            )
        parts.append("")

    if not (blocks or triples or entities):
        parts.append("No data found for this session.")

    return text_result("\n".join(parts))


async def handle_intelligence_ingest(args: dict) -> list[TextContent]:
    """memvault_intelligence_ingest -- publish digest into memvault."""
    result = await to_thread(
        client.intelligence_ingest,
        content=args["content"],
        space_id=args.get("space_id", "default"),
        digest_type=args.get("digest_type", "weekly"),
        period=args.get("period", ""),
    )
    return text_result(
        f"Intelligence digest ingested.\n"
        f"Status: {result.get('status', '?')}\n"
        f"Type: {result.get('digest_type', '?')}\n"
        f"Period: {result.get('period', 'N/A')}\n"
        f"Space: {result.get('space_id', 'default')}"
    )


# ======================== Resources ========================


@server.list_resources()
async def list_resources():
    from mcp.types import Resource

    return [
        Resource(
            uri="memvault://attitudes/current",
            name="attitudes-current",
            description="當前有效的態度事實快照",
            mimeType="text/markdown",
        ),
        Resource(
            uri="memvault://profile/kas",
            name="kas-profile",
            description="KAS 人格檔案（Knowledge/Attitude/Skills 三維量化）",
            mimeType="text/markdown",
        ),
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    try:
        if "attitudes/current" in str(uri):
            result = await to_thread(client.attitudes)
            if not result:
                return "No active attitude facts."
            return "\n\n---\n\n".join(
                f"## [{a['category']}]\n**{a['fact']}**\n"
                f"Confidence: {a.get('confidence', 0.5):.2f} | Operation: {a.get('operation', 'ADD')}"
                for a in result
            )
        if "profile/kas" in str(uri):
            profile = await to_thread(client.profile)
            return (
                f"# KAS Profile\n\n"
                f"- Knowledge: {profile.get('knowledge_score', 0)}\n"
                f"- Attitude: {profile.get('attitude_score', 0)}\n"
                f"- Skill: {profile.get('skill_score', 0)}\n"
                f"- Updated: {profile.get('updated_at', 'N/A')}"
            )
        return f"Unknown resource: {uri}"
    except APIError as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except APIConnectionError as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"memvault error: {type(e).__name__}: {e}"


# ======================== Main ========================


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

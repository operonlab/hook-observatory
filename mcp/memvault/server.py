#!/usr/bin/env python3
"""Memvault MCP Server — Slim adapter — 8 tools + 2 resources.

Each tool = one HTTP call to Core API (localhost:8801).

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

import os
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

CORE_API = os.environ.get("CORE_API_URL", "http://localhost:8801")
SPACE_ID = os.environ.get("MEMVAULT_SPACE_ID", "default")
BASE = f"{CORE_API}/api/memvault"

server = Server("memvault")


# ======================== Helpers ========================


async def api_get(path: str, params: dict | None = None) -> dict:
    """GET request to Core API."""
    p = {"space_id": SPACE_ID}
    if params:
        p.update(params)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE}{path}", params=p)
        resp.raise_for_status()
        return resp.json()


async def api_post(path: str, body: dict | None = None, params: dict | None = None) -> dict:
    """POST request to Core API."""
    p = {"space_id": SPACE_ID}
    if params:
        p.update(params)
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{BASE}{path}", json=body or {}, params=p)
        resp.raise_for_status()
        return resp.json()


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
                "properties": {},
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
            case _:
                return text_result(f"Unknown tool: {name}")
    except httpx.HTTPStatusError as e:
        return text_result(f"API error {e.response.status_code}: {e.response.text}")
    except httpx.ConnectError:
        return text_result(
            f"Cannot connect to Core API at {CORE_API}. "
            "Start the server: cd core && uvicorn src.main:app --port 8801"
        )


# ======================== Tool Implementations ========================


async def handle_recall(args: dict) -> list[TextContent]:
    """memvault_recall -- semantic search, or cascade recall when mode='cascade'."""
    query = args["query"]
    max_results = args.get("max_results", 5)
    mode = args.get("mode", "default")

    # Redirect to KG Cascade Recall when mode=cascade
    if mode == "cascade":
        return await handle_kg_cascade_recall({"query": query, "top_k": max_results})

    # Try semantic search (now GET)
    result = await api_get("/search", {"q": query, "top_k": str(max_results)})
    if result:  # result is now list[SemanticSearchResult]
        blocks_text = "\n\n---\n\n".join(
            f"**[Score {r['score']}]** ({r['block']['block_type']})\n"
            f"Tags: {', '.join(r['block'].get('tags', []))}\n"
            f"{r['block']['content'][:300]}..."
            for r in result
        )
        return text_result(f"Found {len(result)} memories (semantic search)\n\n{blocks_text}")

    # Fallback
    blocks = await api_get("/blocks", {"page_size": str(max_results)})
    if not blocks.get("items"):
        return text_result(f"No matching memories found for: {query}")
    blocks_text = "\n\n---\n\n".join(
        f"**{b['block_type']}**\nTags: {', '.join(b.get('tags', []))}\n{b['content'][:300]}..."
        for b in blocks["items"]
    )
    return text_result(f"Found {blocks['total']} memories (listing)\n\n{blocks_text}")


async def handle_extract(args: dict) -> list[TextContent]:
    """memvault_extract -- POST /blocks (create a new memory block)."""
    body = {
        "content": args["content"],
        "block_type": args.get("block_type", "general"),
        "source_session": args.get("source_session"),
        "tags": args.get("tags", []),
    }
    result = await api_post("/blocks", body)
    return text_result(
        f"Memory extracted and stored.\n"
        f"Block ID: {result['id']}\n"
        f"Type: {result['block_type']}\n"
        f"Tags: {', '.join(result.get('tags', []))}"
    )


async def handle_profile(args: dict) -> list[TextContent]:
    """memvault_profile -- GET /profile (single flat profile)."""
    profile = await api_get("/profile", params={"rebuild": args.get("rebuild", False)})

    return text_result(
        f"# KAS Profile\n\n"
        f"- Knowledge: {profile.get('knowledge_score', 0)}\n"
        f"- Attitude: {profile.get('attitude_score', 0)}\n"
        f"- Skill: {profile.get('skill_score', 0)}\n"
        f"- Updated: {profile.get('updated_at', 'N/A')}"
    )


async def handle_kg_wisdom(args: dict) -> list[TextContent]:
    """memvault_kg_wisdom -- GET /kg/wisdom."""
    params: dict = {}
    if args.get("confidence"):
        params["confidence"] = args["confidence"]
    if args.get("tag"):
        params["tag"] = args["tag"]

    result = await api_get("/kg/wisdom", params if params else None)
    if not result:
        return text_result("No wisdom nodes found.")

    wisdom_text = "\n\n---\n\n".join(
        f"**[{w['confidence']}]** {w['wisdom']}\n"
        f"Bridge: {w['bridge_entity']} | Evidence: {w.get('evidence_count', '?')}"
        + (f"\nTags: {', '.join(w.get('tags', []))}" if w.get("tags") else "")
        for w in result
    )
    return text_result(f"# Wisdom Nodes ({len(result)} total)\n\n{wisdom_text}")


async def handle_kg_cascade_recall(args: dict) -> list[TextContent]:
    """memvault_kg_cascade_recall -- GET /kg/recall."""
    query = args["query"]
    top_k = args.get("top_k", 5)

    result = await api_get("/kg/recall", {"q": query, "top_k": str(top_k)})
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
    """memvault_attitude_current -- GET /kg/attitudes."""
    params: dict = {}
    if args.get("category"):
        params["category"] = args["category"]

    result = await api_get("/kg/attitudes", params if params else None)
    if not result:
        return text_result("No active attitude facts found.")

    facts_text = "\n\n---\n\n".join(
        f"**[{a['category']}]** {a['fact']}\n"
        f"Confidence: {a.get('confidence', 0.5):.2f} | Operation: {a.get('operation', 'ADD')}"
        for a in result
    )
    return text_result(f"# Current Attitudes ({len(result)} active)\n\n{facts_text}")


async def handle_attitude_evolve(args: dict) -> list[TextContent]:
    """memvault_attitude_evolve -- POST /kg/attitudes/evolve."""
    body: dict = {
        "fact": args["fact"],
        "category": args["category"],
    }
    if args.get("source_session"):
        body["source_session"] = args["source_session"]

    result = await api_post("/kg/attitudes/evolve", body)
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
    """memvault_skill_proficiency -- GET /kg/skills/proficiency."""
    result = await api_get("/kg/skills/proficiency")
    if not result:
        return text_result("No skill proficiency data found.")

    rows = "\n".join(
        f"  {i + 1:2d}. {p['skill_name']:<40s} "
        f"proficiency={p.get('proficiency', 0):.2f}  "
        f"invocations={p.get('invocation_count', 0)}  "
        f"success_rate={p.get('success_rate', 0):.0%}"
        for i, p in enumerate(result)
    )
    return text_result(f"# Skill Proficiency Ranking ({len(result)} skills)\n\n{rows}")


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
    if "attitudes/current" in str(uri):
        result = await api_get("/kg/attitudes")
        if not result:
            return "No active attitude facts."
        return "\n\n---\n\n".join(
            f"## [{a['category']}]\n**{a['fact']}**\n"
            f"Confidence: {a.get('confidence', 0.5):.2f} | Operation: {a.get('operation', 'ADD')}"
            for a in result
        )
    if "profile/kas" in str(uri):
        profile = await api_get("/profile")
        return (
            f"# KAS Profile\n\n"
            f"- Knowledge: {profile.get('knowledge_score', 0)}\n"
            f"- Attitude: {profile.get('attitude_score', 0)}\n"
            f"- Skill: {profile.get('skill_score', 0)}\n"
            f"- Updated: {profile.get('updated_at', 'N/A')}"
        )
    return f"Unknown resource: {uri}"


# ======================== Main ========================


async def main():

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

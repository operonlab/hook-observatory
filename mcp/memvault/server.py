#!/usr/bin/env python3
"""Memvault MCP Server — thin adapter over Core API.

Preserves the 9 existing tool names from V1 kas-memory MCP server.
Each tool = one HTTP call to Core API (localhost:8800).

Usage:
    python3 mcp/memvault/server.py

Configure in ~/.claude.json:
    "memvault": {
        "command": "python3",
        "args": ["/path/to/workshop/mcp/memvault/server.py"],
        "env": {
            "CORE_API_URL": "http://localhost:8800",
            "MEMVAULT_SPACE_ID": "default"
        }
    }
"""

import json
import os
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

CORE_API = os.environ.get("CORE_API_URL", "http://localhost:8800")
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


async def api_patch(path: str, body: dict) -> dict:
    """PATCH request to Core API."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.patch(f"{BASE}{path}", json=body)
        resp.raise_for_status()
        return resp.json()


async def api_delete(path: str) -> bool:
    """DELETE request to Core API."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.delete(f"{BASE}{path}")
        return resp.status_code == 204


async def api_put(path: str, body: dict, params: dict | None = None) -> dict:
    """PUT request to Core API."""
    p = {"space_id": SPACE_ID}
    if params:
        p.update(params)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.put(f"{BASE}{path}", json=body, params=p)
        resp.raise_for_status()
        return resp.json()


def text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


# ======================== Tool Definitions ========================


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="kas_recall",
            description="根據 query 搜尋相關記憶（keyword + semantic hybrid search with RRF）",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜尋查詢"},
                    "max_results": {"type": "integer", "default": 5},
                    "min_score": {"type": "number", "default": 0.3},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="kas_extract",
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
            name="kas_search_tags",
            description="根據 tags 精確篩選記憶 blocks",
            inputSchema={
                "type": "object",
                "properties": {
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "type_filter": {"type": "string"},
                },
                "required": ["tags"],
            },
        ),
        Tool(
            name="kas_memory_stats",
            description="查看記憶系統統計（block 數量、tag 分佈、品質指標）",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "default": 30},
                },
            },
        ),
        Tool(
            name="kas_promote",
            description="執行 knowledge promotion（高頻 tag → 知識域晉升）",
            inputSchema={
                "type": "object",
                "properties": {
                    "threshold": {"type": "integer", "default": 3},
                    "dry_run": {"type": "boolean", "default": False},
                    "tag": {"type": "string", "description": "指定單一 tag 晉升"},
                },
            },
        ),
        Tool(
            name="kas_memory_edit",
            description="檢視/刪除/修改特定記憶 block",
            inputSchema={
                "type": "object",
                "properties": {
                    "block_id": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["view", "delete", "update_tags"],
                    },
                    "new_tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["block_id", "action"],
            },
        ),
        Tool(
            name="kas_sync_embeddings",
            description="同步所有記憶 blocks 的 embeddings（pgvector 768d）",
            inputSchema={
                "type": "object",
                "properties": {
                    "lookback_days": {"type": "integer", "default": 30},
                },
            },
        ),
        Tool(
            name="kas_profile",
            description="查看或重建 KAS Profile（Knowledge/Attitude/Skills 三維量化）",
            inputSchema={
                "type": "object",
                "properties": {
                    "rebuild": {"type": "boolean", "default": False},
                },
            },
        ),
        Tool(
            name="kas_skill_search",
            description="搜尋已安裝的 skills（根據 trigger 關鍵字、名稱、domain 匹配）",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        ),
    ]


# ======================== Tool Handlers ========================


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        match name:
            case "kas_recall":
                return await handle_recall(arguments)
            case "kas_extract":
                return await handle_extract(arguments)
            case "kas_search_tags":
                return await handle_search_tags(arguments)
            case "kas_memory_stats":
                return await handle_stats(arguments)
            case "kas_promote":
                return await handle_promote(arguments)
            case "kas_memory_edit":
                return await handle_edit(arguments)
            case "kas_sync_embeddings":
                return await handle_sync_embeddings(arguments)
            case "kas_profile":
                return await handle_profile(arguments)
            case "kas_skill_search":
                return await handle_skill_search(arguments)
            case _:
                return text_result(f"Unknown tool: {name}")
    except httpx.HTTPStatusError as e:
        return text_result(f"API error {e.response.status_code}: {e.response.text}")
    except httpx.ConnectError:
        return text_result(
            f"Cannot connect to Core API at {CORE_API}. "
            "Start the server: cd core && uvicorn src.main:app --port 8800"
        )


# ======================== Tool Implementations ========================


async def handle_recall(args: dict) -> list[TextContent]:
    """kas_recall → GET /search (semantic) + GET /blocks (keyword fallback)."""
    query = args["query"]
    max_results = args.get("max_results", 5)

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
        f"**{b['block_type']}**\n"
        f"Tags: {', '.join(b.get('tags', []))}\n{b['content'][:300]}..."
        for b in blocks["items"]
    )
    return text_result(f"Found {blocks['total']} memories (listing)\n\n{blocks_text}")


async def handle_extract(args: dict) -> list[TextContent]:
    """kas_extract → POST /blocks (create a new memory block)."""
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


async def handle_search_tags(args: dict) -> list[TextContent]:
    """kas_search_tags → GET /blocks?tags=..."""
    tags = args["tags"]
    params = {"tags": ",".join(tags), "page_size": "20"}
    result = await api_get("/blocks", params)

    if not result.get("items"):
        return text_result(f"No blocks matched tags: {', '.join(tags)}")

    blocks_text = "\n\n---\n\n".join(
        f"**{b['block_type']}**\n"
        f"Tags: {', '.join(b.get('tags', []))}\n{b['content'][:500]}"
        for b in result["items"]
    )
    return text_result(
        f"Found {result['total']} blocks matching tags [{', '.join(tags)}]\n\n{blocks_text}"
    )


async def handle_stats(args: dict) -> list[TextContent]:
    """kas_memory_stats → GET /blocks + /tags + /profile."""
    blocks = await api_get("/blocks", {"page_size": "1"})
    tags = await api_get("/tags")
    profile = await api_get("/profile")

    tag_list = "\n".join(f"  {t['name']}: {t['usage_count']}" for t in tags[:20])

    return text_result(
        f"# KAS Memory Stats\n\n"
        f"- Total blocks: {blocks.get('total', 0)}\n"
        f"- Unique tags: {len(tags)}\n\n"
        f"## KAS Scores\n"
        f"- Knowledge Score: {profile.get('knowledge_score', 0)}\n"
        f"- Attitude Score: {profile.get('attitude_score', 0)}\n"
        f"- Skill Score: {profile.get('skill_score', 0)}\n\n"
        f"## Top Tags\n{tag_list}"
    )


async def handle_promote(args: dict) -> list[TextContent]:
    """kas_promote → POST /tags/sync + check frequency → POST /domains."""
    threshold = args.get("threshold", 3)
    dry_run = args.get("dry_run", False)
    target_tag = args.get("tag")

    # Sync tags first
    await api_post("/tags/sync")
    tags = await api_get("/tags")

    # Find tags above threshold
    candidates = [t for t in tags if t["usage_count"] >= threshold]
    if target_tag:
        candidates = [t for t in candidates if t["name"] == target_tag]

    if not candidates:
        return text_result(f"No tags meet promotion threshold ({threshold})")

    # Check which are already domains
    domains = await api_get("/domains")
    existing_names = {d["name"] for d in domains.get("items", [])}

    promoted = []
    for tag in candidates:
        if tag["name"] in existing_names:
            continue
        if dry_run:
            promoted.append(f"  [DRY RUN] Would promote: {tag['name']} ({tag['usage_count']} uses)")
        else:
            await api_post("/domains", {"name": tag["name"]})
            promoted.append(f"  Promoted: {tag['name']} ({tag['usage_count']} uses)")

    if not promoted:
        return text_result("All qualifying tags are already knowledge domains.")

    return text_result(f"Knowledge promotion:\n" + "\n".join(promoted))


async def handle_edit(args: dict) -> list[TextContent]:
    """kas_memory_edit → GET/PATCH/DELETE /blocks/:id."""
    block_id = args["block_id"]
    action = args["action"]

    if action == "view":
        block = await api_get(f"/blocks/{block_id}")
        return text_result(
            f"**{block['block_type']}** (confidence: {block.get('confidence', 0)})\n"
            f"Session: {block.get('source_session', 'N/A')}\n"
            f"Tags: {', '.join(block.get('tags', []))}\n\n"
            f"{block['content']}"
        )

    if action == "delete":
        await api_delete(f"/blocks/{block_id}")
        return text_result(f"Block {block_id} deleted.")

    if action == "update_tags":
        new_tags = args.get("new_tags", [])
        result = await api_patch(f"/blocks/{block_id}", {"tags": new_tags})
        return text_result(
            f"Block {block_id} tags updated.\n"
            f"New tags: {', '.join(result.get('tags', []))}"
        )

    return text_result(f"Unknown action: {action}")


async def handle_sync_embeddings(args: dict) -> list[TextContent]:
    """kas_sync_embeddings — placeholder until EmbeddingService is ready."""
    # TODO: iterate blocks without embeddings, compute via Ollama, update via API
    return text_result(
        "Embedding sync not yet implemented in V2.\n"
        "Waiting for shared EmbeddingService (Ollama nomic-embed-text 768d).\n"
        "Use V1 kas_sync_embeddings for now."
    )


async def handle_profile(args: dict) -> list[TextContent]:
    """kas_profile → GET /profile (single flat profile)."""
    rebuild = args.get("rebuild", False)
    profile = await api_get("/profile")

    return text_result(
        f"# KAS Profile\n\n"
        f"- Knowledge: {profile.get('knowledge_score', 0)}\n"
        f"- Attitude: {profile.get('attitude_score', 0)}\n"
        f"- Skill: {profile.get('skill_score', 0)}\n"
        f"- Updated: {profile.get('updated_at', 'N/A')}"
    )


async def handle_skill_search(args: dict) -> list[TextContent]:
    """kas_skill_search — searches ~/.claude/skills/ directory.

    This tool reads the local skill index, not the Core API.
    Preserved for backward compatibility.
    """
    query = args["query"]
    max_results = args.get("max_results", 5)

    # Use the existing skill index if available
    index_path = os.path.expanduser("~/.claude/data/skill-index/triggers.json")
    if not os.path.exists(index_path):
        return text_result(
            f"Skill index not found at {index_path}.\n"
            "Run: python3 ~/.claude/data/skill-index/build-triggers.py"
        )

    with open(index_path) as f:
        skills = json.load(f)

    query_lower = query.lower()
    scored = []
    for skill in skills:
        score = 0
        name = skill.get("name", "").lower()
        triggers = [t.lower() for t in skill.get("triggers", [])]
        desc = skill.get("description", "").lower()

        if query_lower in name:
            score += 10
        for trigger in triggers:
            if query_lower in trigger:
                score += 5
        if query_lower in desc:
            score += 2

        if score > 0:
            scored.append((score, skill))

    scored.sort(key=lambda x: -x[0])
    results = scored[:max_results]

    if not results:
        return text_result(f'No skills matched query: "{query}"')

    text_parts = "\n\n---\n\n".join(
        f"**{s['name']}** (score: {score})\n{s.get('description', '')[:200]}\n"
        f"Triggers: {', '.join(s.get('triggers', [])[:5])}"
        for score, s in results
    )
    return text_result(f'Found {len(results)} skills for "{query}":\n\n{text_parts}')


# ======================== Resources ========================


@server.list_resources()
async def list_resources():
    from mcp.types import Resource

    return [
        Resource(
            uri="kas://memories/recent",
            name="recent-memories",
            description="最近 14 天的記憶",
            mimeType="text/markdown",
        ),
        Resource(
            uri="kas://knowledge/domains",
            name="knowledge-domains",
            description="所有知識域",
            mimeType="text/markdown",
        ),
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    if "memories/recent" in str(uri):
        blocks = await api_get("/blocks", {"page_size": "50"})
        if not blocks.get("items"):
            return "No recent memories."
        return "\n\n---\n\n".join(
            f"## {b['block_type']}\n"
            f"**Tags**: {', '.join(b.get('tags', []))}\n\n{b['content']}"
            for b in blocks["items"]
        )

    if "knowledge/domains" in str(uri):
        domains = await api_get("/domains")
        items = domains.get("items", [])
        if not items:
            return "No knowledge domains yet."
        return "\n\n---\n\n".join(
            f"# {d['name']}\n> Maturity: {d['maturity']}\n\n{d.get('description', '')}"
            for d in items
        )

    return f"Unknown resource: {uri}"


# ======================== Main ========================


async def main():
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

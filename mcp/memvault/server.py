#!/usr/bin/env python3
"""Memvault MCP Server — thin adapter over Core API.

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

import json
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
            name="memvault_search_tags",
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
            name="memvault_memory_stats",
            description="查看記憶系統統計（block 數量、tag 分佈、品質指標）",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "default": 30},
                },
            },
        ),
        Tool(
            name="memvault_promote",
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
            name="memvault_memory_edit",
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
            name="memvault_sync_embeddings",
            description="同步所有記憶 blocks 的 embeddings（pgvector 768d）",
            inputSchema={
                "type": "object",
                "properties": {
                    "lookback_days": {"type": "integer", "default": 30},
                },
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
            name="memvault_skill_search",
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
        # ---- KG Tools ----
        Tool(
            name="memvault_kg_search",
            description="KG Triple 語意搜尋（semantic search over knowledge graph triples）",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜尋查詢"},
                    "top_k": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="memvault_kg_clusters",
            description="列出 KG 聚類摘要（knowledge graph clusters）",
            inputSchema={
                "type": "object",
                "properties": {},
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
            case "memvault_search_tags":
                return await handle_search_tags(arguments)
            case "memvault_memory_stats":
                return await handle_stats(arguments)
            case "memvault_promote":
                return await handle_promote(arguments)
            case "memvault_memory_edit":
                return await handle_edit(arguments)
            case "memvault_sync_embeddings":
                return await handle_sync_embeddings(arguments)
            case "memvault_profile":
                return await handle_profile(arguments)
            case "memvault_skill_search":
                return await handle_skill_search(arguments)
            case "memvault_kg_search":
                return await handle_kg_search(arguments)
            case "memvault_kg_clusters":
                return await handle_kg_clusters(arguments)
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
    """memvault_recall → semantic search, or cascade recall when mode='cascade'."""
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
    """memvault_extract → POST /blocks (create a new memory block)."""
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
    """memvault_search_tags → GET /blocks?tags=..."""
    tags = args["tags"]
    params = {"tags": ",".join(tags), "page_size": "20"}
    result = await api_get("/blocks", params)

    if not result.get("items"):
        return text_result(f"No blocks matched tags: {', '.join(tags)}")

    blocks_text = "\n\n---\n\n".join(
        f"**{b['block_type']}**\nTags: {', '.join(b.get('tags', []))}\n{b['content'][:500]}"
        for b in result["items"]
    )
    return text_result(
        f"Found {result['total']} blocks matching tags [{', '.join(tags)}]\n\n{blocks_text}"
    )


async def handle_stats(args: dict) -> list[TextContent]:
    """memvault_memory_stats → GET /blocks + /tags + /profile."""
    blocks = await api_get("/blocks", {"page_size": "1"})
    tags = await api_get("/tags")
    profile = await api_get("/profile")

    tag_list = "\n".join(f"  {t['name']}: {t['usage_count']}" for t in tags[:20])

    return text_result(
        f"# Memvault Memory Stats\n\n"
        f"- Total blocks: {blocks.get('total', 0)}\n"
        f"- Unique tags: {len(tags)}\n\n"
        f"## Profile Scores\n"
        f"- Knowledge Score: {profile.get('knowledge_score', 0)}\n"
        f"- Attitude Score: {profile.get('attitude_score', 0)}\n"
        f"- Skill Score: {profile.get('skill_score', 0)}\n\n"
        f"## Top Tags\n{tag_list}"
    )


async def handle_promote(args: dict) -> list[TextContent]:
    """memvault_promote → POST /tags/sync + check frequency → POST /domains."""
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

    return text_result("Knowledge promotion:\n" + "\n".join(promoted))


async def handle_edit(args: dict) -> list[TextContent]:
    """memvault_memory_edit → GET/PATCH/DELETE /blocks/:id."""
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
            f"Block {block_id} tags updated.\nNew tags: {', '.join(result.get('tags', []))}"
        )

    return text_result(f"Unknown action: {action}")


async def handle_sync_embeddings(args: dict) -> list[TextContent]:
    """memvault_sync_embeddings — placeholder until EmbeddingService is ready."""
    # TODO: iterate blocks without embeddings, compute via Ollama, update via API
    return text_result(
        "Embedding sync not yet implemented in V2.\n"
        "Waiting for shared EmbeddingService (Ollama nomic-embed-text 768d).\n"
        "Embedding sync not yet implemented. Use external script for now."
    )


async def handle_profile(args: dict) -> list[TextContent]:
    """memvault_profile → GET /profile (single flat profile)."""
    profile = await api_get("/profile", params={"rebuild": args.get("rebuild", False)})

    return text_result(
        f"# KAS Profile\n\n"
        f"- Knowledge: {profile.get('knowledge_score', 0)}\n"
        f"- Attitude: {profile.get('attitude_score', 0)}\n"
        f"- Skill: {profile.get('skill_score', 0)}\n"
        f"- Updated: {profile.get('updated_at', 'N/A')}"
    )


async def handle_skill_search(args: dict) -> list[TextContent]:
    """memvault_skill_search — searches ~/.claude/skills/ directory.

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


# ======================== KG Tool Implementations ========================


async def handle_kg_search(args: dict) -> list[TextContent]:
    """memvault_kg_search → GET /kg/triples/search."""
    query = args["query"]
    top_k = args.get("top_k", 10)

    result = await api_get("/kg/triples/search", {"q": query, "top_k": str(top_k)})
    if not result:
        return text_result(f"No KG triples found for: {query}")

    triples_text = "\n".join(
        f"  [{i + 1}] {t['subject']} —[{t['predicate']}]→ {t['object']}"
        + (f" (topic: {t['topic']})" if t.get("topic") else "")
        for i, t in enumerate(result)
    )
    return text_result(f'Found {len(result)} KG triples for "{query}":\n\n{triples_text}')


async def handle_kg_clusters(args: dict) -> list[TextContent]:
    """memvault_kg_clusters → GET /kg/clusters."""
    result = await api_get("/kg/clusters")
    if not result:
        return text_result("No KG clusters found.")

    clusters_text = "\n\n---\n\n".join(
        f"**{c['name']}** (size: {c['size']}, verdict: {c.get('verdict', 'UNVERIFIED')})\n"
        f"{c.get('summary', '(no summary)')}"
        for c in result
    )
    return text_result(f"# KG Clusters ({len(result)} total)\n\n{clusters_text}")


async def handle_kg_wisdom(args: dict) -> list[TextContent]:
    """memvault_kg_wisdom → GET /kg/wisdom."""
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
    """memvault_kg_cascade_recall → GET /kg/recall."""
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
            parts.append(f"  {t['subject']} —[{t['predicate']}]→ {t['object']}")
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
    """memvault_attitude_current → GET /kg/attitudes."""
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
    """memvault_attitude_evolve → POST /kg/attitudes/evolve."""
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
    """memvault_skill_proficiency → GET /kg/skills/proficiency."""
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
            uri="memvault://memories/recent",
            name="recent-memories",
            description="最近 14 天的記憶",
            mimeType="text/markdown",
        ),
        Resource(
            uri="memvault://knowledge/domains",
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
            f"## {b['block_type']}\n**Tags**: {', '.join(b.get('tags', []))}\n\n{b['content']}"
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

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())

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

from mcp.server.fastmcp import FastMCP
from workshop.clients._base import APIConnectionError, APIError
from workshop.clients.memvault import MemvaultClient

mcp = FastMCP("memvault")
client = MemvaultClient()


# ======================== Tools ========================


@mcp.tool()
async def memvault_recall(
    query: str,
    max_results: int = 5,
    min_score: float = 0.3,
    mode: str = "default",
    since: str = "",
    before: str = "",
) -> str:
    """根據 query 搜尋相關記憶（keyword + semantic hybrid search with RRF）。mode='cascade' 啟用四層 Cascade Recall"""
    try:
        if mode == "cascade":
            return await memvault_kg_cascade_recall(query=query, top_k=max_results)

        raw = await to_thread(
            client.recall,
            query,
            top_k=max_results,
            min_score=min_score,
            date_from=since or None,
            date_to=before or None,
        )
        results = raw.get("results", []) if isinstance(raw, dict) else raw

        if results:
            blocks_text = "\n\n---\n\n".join(
                f"**[Score {r['score']}]** ({r['block']['block_type']})\n"
                f"Tags: {', '.join(r['block'].get('tags', []))}\n"
                f"{r['block']['content'][:300]}..."
                for r in results
            )
            return f"Found {len(results)} memories (semantic search)\n\n{blocks_text}"

        return f"No matching memories found for: {query}"
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_extract(
    content: str,
    source_session: str = "",
    block_type: str = "general",
    tags: list[str] | None = None,
) -> str:
    """從 session transcript 提煉記憶並存入 memvault"""
    try:
        result = await to_thread(
            client.extract,
            content=content,
            block_type=block_type,
            tags=tags or [],
            source_session=source_session or None,
        )
        return (
            f"Memory extracted and stored.\n"
            f"Block ID: {result['id']}\n"
            f"Type: {result['block_type']}\n"
            f"Tags: {', '.join(result.get('tags', []))}"
        )
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_profile(rebuild: bool = False) -> str:
    """查看或重建 KAS Profile（Knowledge/Attitude/Skills 三維量化）"""
    try:
        profile = await to_thread(client.profile, rebuild=rebuild)
        return (
            f"# KAS Profile\n\n"
            f"- Knowledge: {profile.get('knowledge_score', 0)}\n"
            f"- Attitude: {profile.get('attitude_score', 0)}\n"
            f"- Skill: {profile.get('skill_score', 0)}\n"
            f"- Updated: {profile.get('updated_at', 'N/A')}"
        )
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_kg_wisdom(
    confidence: str = "",
    tag: str = "",
    limit: int = 20,
) -> str:
    """查詢 Wisdom nodes（跨 cluster 提煉的高層洞見）"""
    try:
        result = await to_thread(
            client.wisdom,
            confidence=confidence or None,
            tag=tag or None,
        )
        if not result:
            return "No wisdom nodes found."

        total = len(result)
        items = result[:limit]

        wisdom_text = "\n\n---\n\n".join(
            f"**[{w['confidence']}]** {w['wisdom']}\n"
            f"Bridge: {w['bridge_entity']} | Evidence: {w.get('evidence_count', '?')}"
            + (f"\nTags: {', '.join(w.get('tags', []))}" if w.get("tags") else "")
            for w in items
        )
        truncated = f" (showing {limit} of {total})" if total > limit else ""
        return f"# Wisdom Nodes ({total} total{truncated})\n\n{wisdom_text}"
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_kg_cascade_recall(query: str, top_k: int = 5) -> str:
    """四層 Cascade Recall：L2 Wisdom → L1 Clusters → L0 Triples → Blocks"""
    try:
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

        return "\n".join(parts)
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_attitude_current(category: str = "", limit: int = 20) -> str:
    """查詢當前有效的態度事實（attitude facts，非 superseded）"""
    try:
        result = await to_thread(client.attitudes, category=category or None)
        if not result:
            return "No active attitude facts found."

        total = len(result)
        items = result[:limit]

        facts_text = "\n\n---\n\n".join(
            f"**[{a['category']}]** {a['fact']}\n"
            f"Confidence: {a.get('confidence', 0.5):.2f} | Operation: {a.get('operation', 'ADD')}"
            for a in items
        )
        truncated = f" (showing {limit} of {total})" if total > limit else ""
        return f"# Current Attitudes ({total} active{truncated})\n\n{facts_text}"
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_attitude_evolve(
    fact: str,
    category: str,
    source_session: str = "",
) -> str:
    """態度演化：輸入新 fact，系統判斷 ADD / UPDATE / NOOP（Mem0 pattern）"""
    try:
        result = await to_thread(
            client.attitude_evolve,
            fact=fact,
            category=category,
            source_session=source_session or None,
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

        return "\n".join(lines)
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_skill_proficiency(limit: int = 20) -> str:
    """查詢 Skill 熟練度排行（按 proficiency score 降序）"""
    try:
        result = await to_thread(client.skill_proficiency)
        if not result:
            return "No skill proficiency data found."

        total = len(result)
        items = result[:limit]

        rows = "\n".join(
            f"  {i + 1:2d}. {p['skill_name']:<40s} "
            f"proficiency={p.get('proficiency', 0):.2f}  "
            f"invocations={p.get('invocation_count', 0)}  "
            f"success_rate={p.get('success_rate', 0):.0%}"
            for i, p in enumerate(items)
        )
        truncated = f" (showing {limit} of {total})" if total > limit else ""
        return f"# Skill Proficiency Ranking ({total} skills{truncated})\n\n{rows}"
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_kg_invalidate(
    triple_id: str,
    reason: str = "manual",
    replacement_triple_id: str = "",
) -> str:
    """標記 triple 為無效（軟性時間失效），用於矛盾偵測或手動修正"""
    try:
        result = await to_thread(
            client.invalidate_triple,
            triple_id,
            reason=reason,
            replacement_id=replacement_triple_id or None,
        )
        return (
            f"Triple invalidated.\n"
            f"ID: {result.get('id', '?')}\n"
            f"Subject: {result.get('subject', '?')} → Object: {result.get('object', '?')}\n"
            f"Reason: {result.get('invalidation_reason', 'manual')}"
        )
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_kg_traverse(
    entity: str,
    max_depth: int = 2,
    direction: str = "both",
    predicates: str = "",
    max_results: int = 200,
) -> str:
    """從種子實體出發的多跳圖遍歷（遞迴 CTE），支援方向過濾、predicate 過濾"""
    try:
        result = await to_thread(
            client.graph_traverse,
            entity=entity,
            max_depth=max_depth,
            direction=direction,
            predicates=predicates or None,
            max_results=max_results,
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

        return "\n".join(parts)
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_entity_stats() -> str:
    """實體解析統計：canonical 總數、aliases 總數、平均合併次數、未解析 triples"""
    try:
        result = await to_thread(client.entity_stats)
        return (
            f"# Entity Resolution Stats\n\n"
            f"- Total entities: {result.get('total_entities', 0)}\n"
            f"- Total aliases: {result.get('total_aliases', 0)}\n"
            f"- Avg merge count: {result.get('avg_merge_count', 1.0):.2f}\n"
            f"- Unresolved triples: {result.get('unresolved_triples', 0)}"
        )
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_entity_merge(primary_id: str, secondary_id: str) -> str:
    """合併兩個 canonical entity（secondary → primary），自動更新所有引用的 triples"""
    try:
        result = await to_thread(
            client.merge_entities,
            primary_id,
            secondary_id,
        )
        return (
            f"Entity merge complete.\n"
            f"Canonical: {result.get('canonical_name', '?')}\n"
            f"Aliases: {', '.join(result.get('aliases', []))}\n"
            f"Triples updated: {result.get('triples_updated', 0)}"
        )
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_session_context(source_session: str, space_id: str = "default") -> str:
    """查詢某 session 的完整上下文：blocks + triples + entities（Flywheel cross-reference）"""
    try:
        result = await to_thread(
            client.session_context,
            source_session,
            space_id=space_id,
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

        return "\n".join(parts)
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


@mcp.tool()
async def memvault_intelligence_ingest(
    content: str,
    space_id: str = "default",
    digest_type: str = "weekly",
    period: str = "",
) -> str:
    """將 intelligence digest 注入 memvault（觸發 DIGEST_COMPLETED 事件 → 自動建立 knowledge block + KG triples）"""
    try:
        result = await to_thread(
            client.intelligence_ingest,
            content=content,
            space_id=space_id,
            digest_type=digest_type,
            period=period,
        )
        return (
            f"Intelligence digest ingested.\n"
            f"Status: {result.get('status', '?')}\n"
            f"Type: {result.get('digest_type', '?')}\n"
            f"Period: {result.get('period', 'N/A')}\n"
            f"Space: {result.get('space_id', 'default')}"
        )
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"Unexpected error: {type(e).__name__}: {e}"


# ======================== Resources ========================


@mcp.resource(
    "memvault://attitudes/current",
    name="attitudes-current",
    description="當前有效的態度事實快照",
    mime_type="text/markdown",
)
async def attitudes_current() -> str:
    """當前有效的態度事實快照"""
    try:
        result = await to_thread(client.attitudes)
        if not result:
            return "No active attitude facts."
        return "\n\n---\n\n".join(
            f"## [{a['category']}]\n**{a['fact']}**\n"
            f"Confidence: {a.get('confidence', 0.5):.2f} | Operation: {a.get('operation', 'ADD')}"
            for a in result
        )
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"memvault error: {type(e).__name__}: {e}"


@mcp.resource(
    "memvault://profile/kas",
    name="kas-profile",
    description="KAS 人格檔案（Knowledge/Attitude/Skills 三維量化）",
    mime_type="text/markdown",
)
async def kas_profile() -> str:
    """KAS 人格檔案（Knowledge/Attitude/Skills 三維量化）"""
    try:
        profile = await to_thread(client.profile)
        return (
            f"# KAS Profile\n\n"
            f"- Knowledge: {profile.get('knowledge_score', 0)}\n"
            f"- Attitude: {profile.get('attitude_score', 0)}\n"
            f"- Skill: {profile.get('skill_score', 0)}\n"
            f"- Updated: {profile.get('updated_at', 'N/A')}"
        )
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"memvault error: {type(e).__name__}: {e}"


# ======================== Main ========================

if __name__ == "__main__":
    mcp.run()

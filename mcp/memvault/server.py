#!/usr/bin/env python3
"""Memvault MCP Server — Slim adapter — 17 tools + 2 resources. Uses sdk_client.memvault SDK.

Usage:
    python3 mcp/memvault/server.py

Configure in ~/.claude.json:
    "memvault": {
        "command": "python3",
        "args": ["/path/to/workshop/mcp/memvault/server.py"],
        "env": {
            "CORE_API_URL": "http://localhost:10000",
            "MEMVAULT_SPACE_ID": "default"
        }
    }
"""

from asyncio import to_thread

from mcp.server.fastmcp import FastMCP

from sdk_client._base import APIConnectionError, APIError
from sdk_client.mcp_helpers import mcp_error_handler
from sdk_client.memvault import MemvaultClient

mcp = FastMCP("memvault")
client = MemvaultClient()


# ======================== Tools ========================


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_recall(
    query: str,
    max_results: int = 5,
    min_score: float = 0.3,
    mode: str = "default",
    since: str = "",
    before: str = "",
    as_of: str = "",
) -> str:
    """根據 query 搜尋相關記憶（keyword + semantic hybrid search with RRF）。

    mode='cascade' 啟用四層 Cascade Recall。
    as_of: ISO8601 datetime — 時間旅行（看「過去某時刻已知的事實」），空字串 = 現在視角。
    """
    if mode == "cascade":
        return await memvault_kg_cascade_recall(query=query, top_k=max_results)

    raw = await to_thread(
        client.recall,
        query,
        top_k=max_results,
        min_score=min_score,
        date_from=since or None,
        date_to=before or None,
        as_of=as_of or None,
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


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_extract(
    content: str,
    source_session: str = "",
    block_type: str = "general",
    tags: list[str] | None = None,
) -> str:
    """從 session transcript 提煉記憶並存入 memvault"""
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


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_profile(rebuild: bool = False) -> str:
    """查看或重建 Profile（Knowledge/Attitude 二維量化）"""
    profile = await to_thread(client.profile, rebuild=rebuild)
    return (
        f"# Profile\n\n"
        f"- Knowledge: {profile.get('knowledge_score', 0)}\n"
        f"- Attitude: {profile.get('attitude_score', 0)}\n"
        f"- Updated: {profile.get('updated_at', 'N/A')}"
    )


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_kg_community_summaries(
    resolution_level: int | None = None,
    limit: int = 20,
) -> str:
    """查詢 Community Summaries（Leiden 社群的 LLM 預生成摘要，L2 層）。resolution_level: 0=fine, 1=medium, 2=coarse"""
    result = await to_thread(
        client.list_summaries,
        resolution_level=resolution_level,
    )
    if not result:
        return "No community summaries found. Run synthesis pipeline first."

    total = len(result)
    items = result[:limit]

    summaries_text = "\n\n---\n\n".join(
        f"**Community:** {s.get('community_id', '?')}\n"
        f"{s.get('summary', '(no summary)')}\n"
        f"Key findings: {', '.join(s.get('key_findings', []))}"
        + (f"\nTags: {', '.join(s.get('tags', []))}" if s.get("tags") else "")
        for s in items
    )
    truncated = f" (showing {limit} of {total})" if total > limit else ""
    return f"# Community Summaries ({total} total{truncated})\n\n{summaries_text}"


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_kg_cascade_recall(
    query: str,
    top_k: int = 5,
    skip_routing: bool = False,
    evaluate: str = "default",
    as_of: str = "",
) -> str:
    """Adaptive Cascade Recall：Query Router → L2/L1 Semantic + L0 Triples + Blocks → CRAG Evaluation.

    as_of: ISO8601 datetime — 時間旅行（看「過去某時刻已知的事實」），空字串 = 現在視角。
    """
    result = await to_thread(
        client.cascade,
        query,
        top_k=top_k,
        skip_routing=skip_routing,
        evaluate=evaluate,
        as_of=as_of or None,
    )
    layers = result.get("layers_searched", [])

    parts: list[str] = [
        f'# Cascade Recall: "{query}"',
        f"Layers searched: {', '.join(layers) or 'none'}",
    ]

    # Routing metadata
    routing_intent = result.get("routing_intent")
    if routing_intent:
        parts.append(
            f"Routing: {routing_intent} (confidence: {result.get('routing_confidence', '?'):.2f})"
        )

    # CRAG metadata
    verdict = result.get("evaluation_verdict")
    confidence = result.get("confidence_score")
    if verdict:
        parts.append(f"Quality: {verdict} (confidence: {confidence:.2f})")

    parts.append("")

    summaries = result.get("summaries", [])
    if summaries:
        parts.append(f"## L2 Community Summaries ({len(summaries)})")
        for s in summaries:
            parts.append(f"  {s.get('summary', '?')}")
            findings = s.get("key_findings", [])
            if findings:
                parts.append(f"    Findings: {'; '.join(findings[:3])}")
        parts.append("")

    communities = result.get("communities", [])
    if communities:
        parts.append(f"## L1 Communities ({len(communities)})")
        for c in communities:
            level = c.get("resolution_level", "?")
            parts.append(f"  [L{level}] {c['name']} (size: {c['size']})")
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

    if not (summaries or communities or triples or blocks):
        parts.append("No results found across all layers.")

    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_kg_invalidate(
    triple_id: str,
    reason: str = "manual",
    replacement_triple_id: str = "",
) -> str:
    """標記 triple 為無效（軟性時間失效），用於矛盾偵測或手動修正"""
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


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_kg_traverse(
    entity: str,
    max_depth: int = 2,
    direction: str = "both",
    predicates: str = "",
    max_results: int = 200,
) -> str:
    """從種子實體出發的多跳圖遍歷（遞迴 CTE），支援方向過濾、predicate 過濾"""
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


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_lint(
    checks: str = "all",
    fix: bool = False,
) -> str:
    """知識圖譜健康檢查 — 偵測矛盾、過期、孤立實體、缺失引用、社群異常、資料缺口"""
    result = await to_thread(client.lint, checks=checks, fix=fix, dry_run=not fix)
    findings = result.get("findings", [])
    summary = result.get("summary", {})
    parts = ["# Knowledge Lint Report\n"]
    parts.append(f"Checks: {', '.join(result.get('checks_run', []))}")
    parts.append(f"Duration: {result.get('run_duration_ms', 0):.0f}ms\n")
    for cat, count in summary.items():
        parts.append(f"- **{cat}**: {count} findings")
    if findings:
        parts.append("\n## Findings\n")
        for f in findings[:20]:
            parts.append(f"[{f['severity'].upper()}] {f['check']}: {f['message']}")
    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_entity_stats() -> str:
    """實體解析統計：canonical 總數、aliases 總數、平均合併次數、未解析 triples"""
    result = await to_thread(client.entity_stats)
    return (
        f"# Entity Resolution Stats\n\n"
        f"- Total entities: {result.get('total_entities', 0)}\n"
        f"- Total aliases: {result.get('total_aliases', 0)}\n"
        f"- Avg merge count: {result.get('avg_merge_count', 1.0):.2f}\n"
        f"- Unresolved triples: {result.get('unresolved_triples', 0)}"
    )


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_entity_merge(primary_id: str, secondary_id: str) -> str:
    """合併兩個 canonical entity（secondary → primary），自動更新所有引用的 triples"""
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


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_session_context(source_session: str, space_id: str = "default") -> str:
    """查詢某 session 的完整上下文：blocks + triples + entities（Flywheel cross-reference）"""
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


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_intelligence_ingest(
    content: str,
    space_id: str = "default",
    digest_type: str = "weekly",
    period: str = "",
) -> str:
    """將 intelligence digest 注入 memvault（觸發 DIGEST_COMPLETED 事件 → 自動建立 knowledge block + KG triples）"""
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


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_feedback(
    entity_id: str,
    query: str,
    signal: str = "positive",
    feedback_source: str = "agent",
) -> str:
    """搜尋結果回饋：對 recall 結果標記 positive/negative，影響未來排名（closed-loop learning）"""
    result = await to_thread(
        client.feedback,
        entity_id=entity_id,
        query=query,
        signal=signal,
        feedback_source=feedback_source,
    )
    return (
        f"Feedback recorded.\n"
        f"Entity: {result.get('entity_id', '?')}\n"
        f"Signal: {result.get('signal', '?')}\n"
        f"Source: {result.get('feedback_source', '?')}"
    )


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_query(
    query: str,
    task_mode: str = "auto",
    thinking_mode: str = "auto",
    load_budget: str = "standard",
    consumer: str = "human",
    top_k: int = 6,
) -> str:
    """多層記憶查詢 — main/cascade 雙軌 cards，task_mode 自動推斷意圖。

    task_mode: auto|lookup|decide|build|reflect
    thinking_mode: auto|fast|slow
    load_budget: light|standard|deep
    consumer: human|agent|ui
    """
    result = await to_thread(
        client.query_memory,
        query=query,
        task_mode=task_mode,
        thinking_mode=thinking_mode,
        load_budget=load_budget,
        consumer=consumer,
        top_k=top_k,
    )
    strategy = result.get("strategy", {})
    parts = [
        f'# Memory Query: "{query}"',
        f"Mode: {strategy.get('task_mode', '?')} | Thinking: {strategy.get('thinking_mode_used', '?')} | Budget: {strategy.get('load_budget', '?')}",
        "",
    ]

    for layer, label in [("cards", "Main"), ("cascade_cards", "Cascade")]:
        cards = result.get(layer, [])
        if cards:
            parts.append(f"## {label} Layer ({len(cards)} cards)")
            for c in cards:
                parts.append(f"  **{c.get('title', '?')}** [{c.get('layer', '?')}]")
                parts.append(f"  {c.get('summary', '')[:200]}")
                if c.get("why_relevant"):
                    parts.append(f"  Why: {c['why_relevant']}")
                parts.append("")

    highlights = result.get("highlights", [])
    if highlights:
        parts.append("## Highlights")
        for h in highlights:
            parts.append(f"  - {h}")

    if not any(result.get(k) for k in ("cards", "cascade_cards")):
        parts.append("No memory cards found.")

    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_inject(
    query: str,
    task_mode: str = "build",
    thinking_mode: str = "auto",
    load_budget: str = "light",
    top_k: int = 6,
) -> str:
    """Agent system prompt 記憶注入 — 回傳預格式化的 system_prompt_memory + working_context"""
    result = await to_thread(
        client.inject,
        query=query,
        task_mode=task_mode,
        thinking_mode=thinking_mode,
        load_budget=load_budget,
        top_k=top_k,
    )
    parts = [
        f'# Memory Injection: "{query}"',
        "",
        "## System Prompt Memory",
        result.get("system_prompt_memory", "(empty)"),
        "",
    ]

    working = result.get("working_context")
    if working:
        parts.append("## Working Context")
        parts.append(working)
        parts.append("")

    bias = result.get("decision_bias")
    if bias:
        parts.append("## Decision Bias")
        parts.append(bias)

    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("Memvault")
async def memvault_inspect(
    query: str,
    task_mode: str = "reflect",
    load_budget: str = "deep",
    top_k: int = 6,
) -> str:
    """深度記憶檢視 — 慢思考模式，完整證據鏈 + raw sections"""
    result = await to_thread(
        client.inspect,
        query=query,
        task_mode=task_mode,
        load_budget=load_budget,
        top_k=top_k,
    )
    strategy = result.get("strategy", {})
    parts = [
        f'# Memory Inspection: "{query}"',
        f"Mode: {strategy.get('task_mode', '?')} | Thinking: slow | Budget: {strategy.get('load_budget', '?')}",
        "",
    ]

    cards = result.get("cards", [])
    if cards:
        parts.append(f"## Cards ({len(cards)})")
        for c in cards:
            parts.append(f"### {c.get('title', '?')} [{c.get('layer', '?')}]")
            parts.append(c.get("summary", ""))
            refs = c.get("evidence_refs", [])
            if refs:
                parts.append("Evidence:")
                for r in refs[:5]:
                    parts.append(f"  - [{r.get('kind', '?')}] {r.get('title', '?')}: {r.get('snippet', '')[:100]}")
            parts.append("")

    for section, label in [("fast", "Fast"), ("cascade", "Cascade")]:
        raw = result.get("raw_sections", {}).get(section)
        if raw:
            parts.append(f"## Raw {label} Section")
            parts.append(str(raw)[:500])
            parts.append("")

    if not cards:
        parts.append("No inspection results found.")

    return "\n".join(parts)


@mcp.tool()
@mcp_error_handler("Memvault")
async def annotate_insight(
    insight: str,
    block_type: str = "knowledge",
    tags: list[str] | None = None,
    importance: float = 0.7,
) -> str:
    """即時標注知識洞見：直接建立 memory block，適合 realtime sideband 快速記錄。

    Args:
        insight: 知識內容（完整文字）
        block_type: 區塊類型，可選 knowledge / decision / pattern / insight
        tags: 額外標籤（自動附加 realtime-annotation）
        importance: 重要度 0.0–1.0（預設 0.7）
    """
    import os

    topic = insight[:15]
    all_tags = list(tags or []) + ["realtime-annotation"]
    api_url = os.environ.get("MEMVAULT_API_URL", "http://127.0.0.1:10000/api/memvault")

    body: dict = {
        "content": insight,
        "block_type": block_type,
        "tags": all_tags,
        "topic": topic,
        "importance": importance,
        "source": "annotate_insight_tool",
    }

    import httpx as _httpx

    try:
        async with _httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"{api_url}/blocks",
                json=body,
                params={"space_id": client.space_id},
                headers={"X-Internal-Key": client._internal_key} if client._internal_key else {},
            )
            resp.raise_for_status()
            result = resp.json()
    except _httpx.ConnectError:
        return f"Error: 無法連線至 Memvault API（{api_url}）"
    except _httpx.HTTPStatusError as e:
        return f"Error: API 回傳 {e.response.status_code} — {e.response.text[:200]}"
    except _httpx.RequestError as e:
        return f"Error: 請求失敗 — {type(e).__name__}: {e}"

    return (
        f"Insight annotated.\n"
        f"Block ID: {result.get('id', '?')}\n"
        f"Type: {result.get('block_type', block_type)}\n"
        f"Topic: {result.get('topic', topic)}\n"
        f"Tags: {', '.join(result.get('tags', all_tags))}\n"
        f"Importance: {importance}"
    )


# ======================== Resources ========================


@mcp.resource(
    "memvault://attitudes/current",
    name="attitudes-current",
    description="當前有效的態度事實快照 (block_type=attitude)",
    mime_type="text/markdown",
)
async def attitudes_current() -> str:
    """當前有效的態度 blocks 快照"""
    try:
        result = await to_thread(client.list_blocks, block_type="attitude", page_size=50)
        items = result.get("items", []) if isinstance(result, dict) else result
        if not items:
            return "No active attitude blocks."
        return "\n\n---\n\n".join(
            f"## {', '.join(b.get('tags', ['untagged']))}\n"
            f"**{b.get('content', '')[:300]}**\n"
            f"Created: {b.get('created_at', 'N/A')}"
            for b in items
        )
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"memvault error: {type(e).__name__}: {e}"


@mcp.resource(
    "memvault://profile/kas",
    name="kas-profile",
    description="Profile（Knowledge/Attitude 二維量化）",
    mime_type="text/markdown",
)
async def kas_profile() -> str:
    """Profile（Knowledge/Attitude 二維量化）"""
    try:
        profile = await to_thread(client.profile)
        return (
            f"# Profile\n\n"
            f"- Knowledge: {profile.get('knowledge_score', 0)}\n"
            f"- Attitude: {profile.get('attitude_score', 0)}\n"
            f"- Updated: {profile.get('updated_at', 'N/A')}"
        )
    except (APIError, APIConnectionError) as e:
        return f"memvault error: {type(e).__name__}: {e}"
    except Exception as e:
        return f"memvault error: {type(e).__name__}: {e}"


# ======================== Main ========================

if __name__ == "__main__":
    mcp.run()

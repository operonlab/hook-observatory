"""DocVault MCP Server — 12 tools for document knowledge QA.

Usage:
    python3 mcp/docvault/server.py

Configure in ~/.mcpproxy/mcp_config.json:
    "docvault": {
        "command": "python3",
        "args": ["/path/to/workshop/mcp/docvault/server.py"],
        "env": {
            "CORE_API_URL": "http://localhost:10000",
            "DOCVAULT_SPACE_ID": "default"
        }
    }
"""

import os

from mcp.server.fastmcp import FastMCP

from sdk_client.docvault import DocvaultClient
from sdk_client.mcp_helpers import mcp_error_handler

mcp = FastMCP("docvault")
client = DocvaultClient()

SPACE_ID = os.getenv("DOCVAULT_SPACE_ID", "default")


def _fmt_doc(doc: dict) -> str:
    tags = ", ".join(doc.get("tags", []))
    return (
        f"📄 {doc['title']} [{doc.get('status', '?')}]\n"
        f"   ID: {doc['id']}  Type: {doc.get('source_type', '?')}\n"
        f"   Tags: {tags or 'none'}\n"
        f"   Confidence: {doc.get('confidence', 'N/A')}"
    )


def _fmt_citation(c: dict) -> str:
    parts = [f"  [{c.get('section', '')}]"]
    if c.get("page"):
        parts.append(f"p.{c['page']}")
    if c.get("quote"):
        parts.append(f'"{c["quote"][:100]}..."')
    return " ".join(parts)


# ======================== Tool 1: Upload ========================


@mcp.tool()
@mcp_error_handler("DocVault")
async def docvault_upload(
    title: str,
    content_hash: str,
    source_type: str = "markdown",
    source_uri: str = "",
    tags: str = "",
) -> str:
    """上傳文件到 DocVault。tags 用逗號分隔。"""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    result = client.create(
        title=title,
        content_hash=content_hash,
        source_type=source_type,
        source_uri=source_uri,
        tags=tag_list,
        space_id=SPACE_ID,
    )
    return f"✅ Document uploaded: {result['id']}\n{_fmt_doc(result)}"


# ======================== Tool 2: Search ========================


@mcp.tool()
@mcp_error_handler("DocVault")
async def docvault_search(
    query: str,
    top_k: int = 10,
) -> str:
    """語義搜尋文件 chunks。"""
    results = client.search(query=query, top_k=top_k, space_id=SPACE_ID)
    if not results.get("results"):
        return "No results found."

    lines = [f"🔍 Found {len(results['results'])} results for: {query}\n"]
    for i, r in enumerate(results["results"][:top_k], 1):
        section = r.get("section_path", "")
        content = r.get("content", "")[:150]
        lines.append(f"{i}. [{section}] {content}...")
    return "\n".join(lines)


# ======================== Tool 3: QA ========================


@mcp.tool()
@mcp_error_handler("DocVault")
async def docvault_qa(
    question: str,
    domain: str = "default",
    top_k: int = 6,
) -> str:
    """問答(Pipeline A — 事實回答 + citation)。"""
    result = client.qa(
        question=question,
        mode="factual",
        domain=domain,
        top_k=top_k,
        space_id=SPACE_ID,
    )
    citations = result.get("citations", [])
    cite_text = "\n".join(_fmt_citation(c) for c in citations) if citations else "  (no citations)"

    return (
        f"💡 Answer (confidence: {result.get('confidence', 'N/A')}, "
        f"verdict: {result.get('crag_verdict', 'N/A')}):\n\n"
        f"{result.get('answer', 'No answer')}\n\n"
        f"📎 Citations:\n{cite_text}"
    )


# ======================== Tool 4: Mixed QA ========================


@mcp.tool()
@mcp_error_handler("DocVault")
async def docvault_qa_mixed(
    question: str,
    domain: str = "default",
    top_k: int = 6,
) -> str:
    """混合查詢(Pipeline C — memvault ∥ docvault merge)。"""
    result = client.qa(
        question=question,
        mode="mixed",
        domain=domain,
        top_k=top_k,
        space_id=SPACE_ID,
    )
    citations = result.get("citations", [])
    cite_text = "\n".join(_fmt_citation(c) for c in citations) if citations else "  (no citations)"

    return (
        f"🔀 Mixed Answer (pipeline: C, confidence: {result.get('confidence', 'N/A')}):\n\n"
        f"{result.get('answer', 'No answer')}\n\n"
        f"📎 Citations:\n{cite_text}"
    )


# ======================== Tool 5: Info ========================


@mcp.tool()
@mcp_error_handler("DocVault")
async def docvault_info(document_id: str) -> str:
    """取得文件詳細資訊 + 版本歷史。"""
    doc = client.get(document_id, space_id=SPACE_ID)
    lines = [_fmt_doc(doc), ""]

    versions = client.list_versions(document_id, space_id=SPACE_ID)
    if versions.get("items"):
        lines.append("📋 Versions:")
        for v in versions["items"]:
            lines.append(
                f"  v{v['version_number']} [{v['status']}] "
                f"chunks={v.get('chunk_count', 0)} "
                f"model={v.get('extraction_model', 'N/A')}"
            )
    return "\n".join(lines)


# ======================== Tool 6: Relations ========================


@mcp.tool()
@mcp_error_handler("DocVault")
async def docvault_relations(document_id: str) -> str:
    """查看文件的關係圖(cites, extends, contradicts, supersedes)。"""
    result = client.list_relations(document_id, space_id=SPACE_ID)
    items = result.get("items", [])
    if not items:
        return f"No relations found for document {document_id[:8]}."

    lines = [f"🔗 Relations for {document_id[:8]}:\n"]
    for r in items:
        src = r.get("source_document_id", "")[:8]
        tgt = r.get("target_document_id", "")[:8]
        rel = r.get("relation_type", "?")
        conf = r.get("confidence", "N/A")
        lines.append(f"  {src} —[{rel}]→ {tgt}  (confidence: {conf})")
    return "\n".join(lines)


# ======================== Tool 7: Contradictions ========================


@mcp.tool()
@mcp_error_handler("DocVault")
async def docvault_contradictions(document_id: str) -> str:
    """偵測指定文件的矛盾關係。"""
    result = client.find_contradictions(document_id, space_id=SPACE_ID)
    if not result:
        return f"No contradictions found for document {document_id[:8]}."

    lines = [f"⚠️ Contradictions for {document_id[:8]}:\n"]
    for c in result:
        lines.append(
            f"  vs. {c.get('other_document_title', '?')} "
            f"({c.get('other_document_id', '')[:8]})\n"
            f"    Evidence: {c.get('evidence', 'N/A')[:100]}\n"
            f"    Confidence: {c.get('confidence', 'N/A')}"
        )
    return "\n".join(lines)


# ======================== Tool 8: Coverage Gaps ========================


@mcp.tool()
@mcp_error_handler("DocVault")
async def docvault_gaps(status: str = "pending") -> str:
    """列出覆蓋缺口(CRAG INCORRECT 時自動建立)。"""
    result = client.list_gaps(status=status, space_id=SPACE_ID)
    items = result.get("items", [])
    if not items:
        return f"No coverage gaps with status '{status}'."

    lines = [f"🕳️ Coverage Gaps ({status}): {len(items)}\n"]
    for g in items:
        lines.append(
            f"  [{g.get('gap_type', '?')}] {g.get('query_text', '')[:80]}\n"
            f"    Hash: {g.get('query_hash', '')[:12]}  Status: {g.get('status', '?')}"
        )
    return "\n".join(lines)


# ======================== Tool 9: Supersede ========================


@mcp.tool()
@mcp_error_handler("DocVault")
async def docvault_supersede(
    document_id: str,
    new_content_hash: str,
) -> str:
    """更新文件版本(content_hash 不同 → 新版本, 舊版 superseded)。"""
    result = client.supersede(
        document_id=document_id,
        content_hash=new_content_hash,
        space_id=SPACE_ID,
    )
    return (
        f"✅ Document superseded: v{result.get('version_number', '?')}\n"
        f"   New version ID: {result.get('id', 'N/A')}"
    )


# ======================== Tool 10: Stats ========================


@mcp.tool()
@mcp_error_handler("DocVault")
async def docvault_stats() -> str:
    """統計概覽(文件數, chunks, QA logs, coverage gaps)。"""
    result = client.dashboard(space_id=SPACE_ID)
    return (
        f"📊 DocVault Stats:\n"
        f"  Documents: {result.get('total_documents', 0)} "
        f"(published: {result.get('published_count', 0)})\n"
        f"  Chunks: {result.get('total_chunks', 0)}\n"
        f"  QA Logs: {result.get('total_qa_logs', 0)}\n"
        f"  Coverage Gaps: {result.get('coverage_gap_count', 0)}"
    )


# ======================== Tool 11: Feedback ========================


@mcp.tool()
@mcp_error_handler("DocVault")
async def docvault_feedback(
    qa_log_id: str,
    feedback: str = "positive",
) -> str:
    """對 QA 結果提供反饋(positive/negative)。"""
    client.qa_feedback(qa_log_id=qa_log_id, feedback=feedback, space_id=SPACE_ID)
    return f"✅ Feedback recorded: {feedback} for QA log {qa_log_id[:8]}"


# ======================== Tool 12: Bulk Import ========================


@mcp.tool()
@mcp_error_handler("DocVault")
async def docvault_bulk_import(
    directory: str,
    source_type: str = "markdown",
    tags: str = "",
) -> str:
    """批量匯入目錄中的文件。tags 用逗號分隔。"""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    result = client.bulk_import(
        directory=directory,
        source_type=source_type,
        tags=tag_list,
        space_id=SPACE_ID,
    )
    success = result.get("success", 0)
    failed = result.get("failed", 0)
    return (
        f"📦 Bulk Import Complete:\n"
        f"  Success: {success}  Failed: {failed}\n"
        f"  Total: {success + failed}"
    )


# ======================== Main ========================

if __name__ == "__main__":
    mcp.run()

"""Build LLM context based on mode (workshop / blog)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Module display names for context hints
MODULE_HINTS: dict[str, str] = {
    "finance": "財務管理（交易、預算、訂閱）",
    "taskflow": "任務管理（任務、分派、獎勵）",
    "ideagraph": "知識圖譜（靈感、連結）",
    "intelflow": "情報流（RSS、每日簡報）",
    "memvault": "記憶庫（語意搜尋、知識圖譜）",
    "briefing": "每日簡報（多分析師辯論摘要）",
    "capture": "快速捕捉（模糊輸入解析）",
    "dailyos": "每日系統（計畫、方法論）",
    "invest": "投資追蹤（投資組合分析）",
    "notification": "通知中心（多管道通知）",
    "nodeflow": "工作流（DAG 編排）",
    "paper": "論文管理（arXiv 搜尋、摘要）",
    "admin": "系統管理（審計日誌）",
}

WORKSHOP_SYSTEM = (
    "你是 Workshop 的助手精靈，用繁體中文回答。\n"
    "根據以下 context 回答用戶的問題。\n"
    "如果 context 中沒有足夠資訊，請如實說明，不要編造答案。\n"
    "回答要簡潔、直接、有幫助。"
)

BLOG_SYSTEM = (
    "你是部落格助手精靈，用繁體中文回答。\n"
    "只根據以下部落格文章內容回答問題。\n"
    "如果文章中沒有相關資訊，請說明「目前的文章中沒有提到這個主題」。\n"
    "不要回答文章範圍外的問題。"
)


async def build_workshop_context(
    message: str,
    module: str | None,
    space_id: str,
    db,
) -> list[dict]:
    """Build context for workshop mode using memvault search."""
    context_parts: list[str] = []

    # 1. Memvault semantic search
    try:
        from src.modules.memvault.services import memory_block_service
        from src.shared.embedding import get_embedding

        query_embedding = await get_embedding(message, task_type="search_query")
        if query_embedding:
            result = await memory_block_service.qdrant_search(
                db=db,
                space_id=space_id,
                query=message,
                query_embedding=query_embedding,
                top_k=5,
            )
            if result:
                items, _meta = result
                if items:
                    memories = "\n".join(f"- {item.content[:500]}" for item in items[:5])
                    context_parts.append(f"## 相關記憶\n{memories}")
    except Exception:
        logger.warning("Memvault search failed, proceeding without context", exc_info=True)

    # 2. Module hint
    if module and module in MODULE_HINTS:
        context_parts.append(f"## 當前模組\n用戶正在使用「{MODULE_HINTS[module]}」模組。")

    system_content = WORKSHOP_SYSTEM
    if context_parts:
        system_content += "\n\n" + "\n\n".join(context_parts)

    return [{"role": "system", "content": system_content}]


async def build_blog_context(
    message: str,
    space_id: str,
    db,
) -> list[dict]:
    """Build context for blog mode using memvault search with blog tag."""
    context_parts: list[str] = []

    try:
        from src.modules.memvault.services import memory_block_service
        from src.shared.embedding import get_embedding

        query_embedding = await get_embedding(message, task_type="search_query")
        if query_embedding:
            result = await memory_block_service.qdrant_search(
                db=db,
                space_id=space_id,
                query=message,
                query_embedding=query_embedding,
                top_k=3,
                tags=["blog"],
            )
            if result:
                items, _meta = result
                if items:
                    articles = "\n\n".join(f"### {item.content[:1000]}" for item in items[:3])
                    context_parts.append(f"## 相關文章\n{articles}")
    except Exception:
        logger.warning("Blog memvault search failed", exc_info=True)

    system_content = BLOG_SYSTEM
    if context_parts:
        system_content += "\n\n" + "\n\n".join(context_parts)
    else:
        system_content += "\n\n（目前沒有找到相關的部落格文章）"

    return [{"role": "system", "content": system_content}]


async def build_context(
    mode: str,
    message: str,
    module: str | None,
    space_id: str,
    db,
) -> list[dict]:
    """Build LLM messages based on mode."""
    if mode == "workshop":
        return await build_workshop_context(message, module, space_id, db)
    elif mode == "blog":
        return await build_blog_context(message, space_id, db)
    else:
        return [{"role": "system", "content": WORKSHOP_SYSTEM}]

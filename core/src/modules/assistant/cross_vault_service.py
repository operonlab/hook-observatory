"""Cross-vault QA dispatch — fan out a single question to memvault and/or
docvault based on the router's intent classification, then merge citations.

Calls each vault's public services.py API (architecture.md HARD RULE: no
model imports across modules; only `<module>.services` entry points).

Intent semantics:
- memory: only memvault.qdrant_search; answer is a brief synthesis of the
  top blocks (no docvault LLM round-trip).
- doc:    only docvault.QAService.ask (full pipeline + citations).
- mixed:  both, concurrently; docvault answer wins as the synthesized text
  because docvault has the LLM synthesizer wired; memvault hits become
  additional citations.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .ops.query_router import classify_intent
from .schemas import AssistantQARequest, AssistantQAResponse, CrossVaultCitation

logger = logging.getLogger(__name__)


async def _recall_memvault(
    db: AsyncSession,
    query: str,
    space_id: str,
    top_k: int,
) -> list[Any]:
    """Best-effort memvault recall. Returns [] on any failure."""
    try:
        from src.modules.memvault.services import memory_block_service
        from src.shared.embedding import get_embedding

        embedding = await get_embedding(query, task_type="search_query")
        if not embedding:
            return []
        result = await memory_block_service.qdrant_search(
            db=db,
            space_id=space_id,
            query=query,
            query_embedding=embedding,
            top_k=top_k,
        )
        if not result:
            return []
        items, _meta = result
        return list(items)
    except Exception:
        logger.warning("cross_vault: memvault recall failed", exc_info=True)
        return []


async def _ask_docvault(
    db: AsyncSession,
    request: AssistantQARequest,
    space_id: str,
    created_by: str | None,
) -> Any | None:
    """Best-effort docvault QA. Returns None on any failure."""
    try:
        from src.modules.docvault.qa_service import QAService
        from src.modules.docvault.schemas import QARequest

        dv_request = QARequest(
            question=request.question,
            mode=request.docvault_mode,
            top_k=request.docvault_top_k,
            session_id=request.session_id,
            tags=request.docvault_tags,
        )
        dv_space = request.docvault_space or space_id
        return await QAService().ask(
            db=db,
            request=dv_request,
            space_id=dv_space,
            created_by=created_by,
        )
    except Exception:
        logger.warning("cross_vault: docvault QA failed", exc_info=True)
        return None


def _memvault_to_citation(item: Any) -> CrossVaultCitation:
    """Pull only public-shape fields off whatever memvault returns."""
    content = getattr(item, "content", None) or ""
    return CrossVaultCitation(
        source="memvault",
        block_id=str(getattr(item, "id", "") or "") or None,
        block_content=content[:600] if content else None,
        block_type=getattr(item, "block_type", None),
        score=getattr(item, "final_score", None) or getattr(item, "score", None),
    )


def _docvault_citation_to_cv(cit: Any) -> CrossVaultCitation:
    return CrossVaultCitation(
        source="docvault",
        document_id=getattr(cit, "document_id", None),
        chunk_id=getattr(cit, "chunk_id", None),
        section=getattr(cit, "section", None),
        quote=getattr(cit, "quote", None),
    )


def _synthesize_from_memvault(items: list[Any], question: str) -> str:
    """When intent=memory we don't pay for a docvault LLM round-trip; instead
    return a short stitched-together brief from the top blocks.

    Not pretty, but explicit — caller sees the raw memvault content and the
    citations carry the full context.
    """
    if not items:
        return "（memvault 沒有找到相關記憶）"
    bullets = []
    for i, it in enumerate(items[:5], start=1):
        content = (getattr(it, "content", "") or "").strip()
        if not content:
            continue
        snippet = content[:240].replace("\n", " ")
        bullets.append(f"[{i}] {snippet}")
    if not bullets:
        return "（memvault 命中但內容空白）"
    return f"根據 memvault 內 {len(items)} 條相關記憶：\n" + "\n".join(bullets)


async def cross_vault_qa(
    db: AsyncSession,
    request: AssistantQARequest,
    space_id: str,
    created_by: str | None = None,
) -> AssistantQAResponse:
    """Run the router → dispatch → merge pipeline for one question."""
    # 1. Resolve intent
    if request.routing == "auto":
        classified = await classify_intent(request.question)
        intent = str(classified.get("intent", "mixed"))
        routing_model = str(classified.get("model", "") or "")
        routing_fallback = bool(classified.get("fallback", False))
    else:
        intent = request.routing
        routing_model = "user-specified"
        routing_fallback = False

    # 2. Fan out (concurrent when mixed)
    mem_items: list[Any] = []
    dv_response: Any | None = None
    if intent == "memory":
        mem_items = await _recall_memvault(
            db, request.question, space_id, request.memvault_top_k
        )
    elif intent == "doc":
        dv_response = await _ask_docvault(db, request, space_id, created_by)
    else:  # mixed
        mem_items, dv_response = await asyncio.gather(
            _recall_memvault(db, request.question, space_id, request.memvault_top_k),
            _ask_docvault(db, request, space_id, created_by),
        )

    # 3. Build merged citations + answer
    citations: list[CrossVaultCitation] = []
    citations.extend(_memvault_to_citation(it) for it in mem_items[: request.memvault_top_k])
    dv_hits = 0
    if dv_response is not None:
        dv_citations = getattr(dv_response, "citations", []) or []
        citations.extend(_docvault_citation_to_cv(c) for c in dv_citations)
        dv_hits = len(dv_citations)

    if dv_response is not None and getattr(dv_response, "answer", ""):
        answer = dv_response.answer
    else:
        answer = _synthesize_from_memvault(mem_items, request.question)

    return AssistantQAResponse(
        question=request.question,
        answer=answer,
        routing_decision=intent,
        routing_model=routing_model,
        routing_fallback=routing_fallback,
        memvault_hits=len(mem_items),
        docvault_hits=dv_hits,
        citations=citations,
        docvault_qa_log_id=getattr(dv_response, "qa_log_id", None) if dv_response else None,
    )

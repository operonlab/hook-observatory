"""DocVault QA Service — Pipeline A/B/C orchestration.

Assembles domain-specific QA pipelines from Slot-based Ops defined in domain_profiles.py.
Uses shared reactive Pipeline infrastructure.

Pipeline A: Top-Down factual QA (embed → search → rerank → CRAG → synth)
Pipeline B: Bottom-Up coverage expansion (gap detection → analysis → conditional ingest)
Pipeline C: Mixed query (fan-out memvault ∥ docvault → merge → rerank → CRAG → synth)
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING, Any

from .domain_profiles import get_profile, resolve_op
from .schemas import CitationRef, QARequest, QAResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _enrich_citations_with_signal(
    citations: list[dict],
    *,
    overall_confidence: float,
    crag_verdict: str | None,
) -> list[CitationRef]:
    """Attach confidence + confidence_type to each citation (Phase B Phase 2026-05-11).

    Rules (graphify-cannibalized three-tier):
      - If crag_verdict == 'incorrect' → all citations forced to 'ambiguous'
      - Otherwise use per-citation score if present, else overall_confidence
      - score >= 0.8 → 'extracted', 0.4 <= score < 0.8 → 'inferred', else 'ambiguous'

    If citation dict already carries explicit confidence/confidence_type,
    do not overwrite (synth op authority preserved).
    """
    from src.modules.memvault.crag_evaluator import signal_from_score

    forced_ambiguous = crag_verdict == "incorrect"
    enriched: list[CitationRef] = []
    for c in citations:
        c2 = dict(c)
        if "confidence" not in c2 or c2["confidence"] is None:
            c2["confidence"] = c.get("score", overall_confidence)
        if "confidence_type" not in c2 or c2["confidence_type"] is None:
            if forced_ambiguous:
                c2["confidence_type"] = "ambiguous"
            else:
                c2["confidence_type"] = signal_from_score(c2["confidence"])
        enriched.append(CitationRef(**c2))
    return enriched


def _hash_query(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()


class QAService:
    """Orchestrates QA pipelines using domain profiles and Slot-based Ops."""

    async def ask(
        self,
        db: AsyncSession,
        request: QARequest,
        space_id: str = "default",
        created_by: str | None = None,
    ) -> QAResponse:
        """Execute a QA pipeline based on request mode and domain.

        Args:
            db: Database session.
            request: QA request with question, mode, domain, top_k.
            space_id: Space scope.
            created_by: User ID for audit trail.

        Returns:
            QAResponse with answer, citations, confidence, verdict.
        """
        start_ms = time.monotonic()

        if request.mode == "mixed":
            result = await self._pipeline_c(db, request, space_id)
        else:
            result = await self._pipeline_a(db, request, space_id)

        elapsed_ms = int((time.monotonic() - start_ms) * 1000)

        # Log QA execution
        qa_log_id = await self._record_qa_log(
            db,
            query=request.question,
            answer=result.get("answer", ""),
            citations=result.get("citations", []),
            confidence=result.get("confidence", 0.0),
            crag_verdict=result.get("crag_verdict"),
            pipeline_used="C" if request.mode == "mixed" else "A",
            latency_ms=elapsed_ms,
            space_id=space_id,
            created_by=created_by,
        )

        enriched_citations = _enrich_citations_with_signal(
            result.get("citations", []),
            overall_confidence=result.get("confidence", 0.0),
            crag_verdict=result.get("crag_verdict"),
        )
        return QAResponse(
            question=request.question,
            answer=result.get("answer", ""),
            citations=enriched_citations,
            confidence=result.get("confidence", 0.0),
            crag_verdict=result.get("crag_verdict"),
            pipeline_used="C" if request.mode == "mixed" else "A",
            qa_log_id=qa_log_id,
        )

    async def _pipeline_a(
        self,
        db: AsyncSession,
        request: QARequest,
        space_id: str,
    ) -> dict[str, Any]:
        """Pipeline A — Top-Down factual QA.

        Steps: Embed → Search → Rerank → CRAG → Synth
        """
        profile = get_profile(request.domain)
        ctx: dict[str, Any] = {
            "question": request.question,
            "top_k": request.top_k,
            "space_id": space_id,
            "domain": request.domain,
            "db": db,
        }

        # Step 1: Search (SearchSlot)
        search_op_cls = resolve_op(profile["search"])
        if search_op_cls:
            search_op = search_op_cls()
            ctx = await search_op(ctx)
        else:
            logger.warning(
                "SearchSlot op %s not registered, using empty results",
                profile["search"],
            )
            ctx["evidence_chunks"] = []

        # Step 2: Rerank (RerankSlot)
        rerank_op_cls = resolve_op(profile["rerank"])
        if rerank_op_cls:
            rerank_op = rerank_op_cls()
            ctx = await rerank_op(ctx)

        # Step 3: CRAG evaluation
        ctx = await self._evaluate_crag(ctx)

        # Step 4: Synthesize (SynthSlot)
        synth_op_cls = resolve_op(profile["synth"])
        if synth_op_cls:
            synth_op = synth_op_cls()
            ctx = await synth_op(ctx)
        else:
            ctx["answer"] = "Synthesis operator not available."
            ctx["citations"] = []
            ctx["confidence"] = 0.0

        return ctx

    async def _pipeline_c(
        self,
        db: AsyncSession,
        request: QARequest,
        space_id: str,
    ) -> dict[str, Any]:
        """Pipeline C — Mixed query (memvault ∥ docvault → merge → answer).

        Fan-out to both knowledge sources, merge results, then synthesize.
        """
        profile = get_profile(request.domain)
        ctx: dict[str, Any] = {
            "question": request.question,
            "top_k": request.top_k,
            "space_id": space_id,
            "domain": request.domain,
            "db": db,
        }

        # FanOut: parallel search across memvault + docvault
        fan_out_cls = resolve_op("FanOutOp")
        if fan_out_cls:
            fan_out = fan_out_cls()
            ctx = await fan_out(ctx)
        else:
            # Fallback: just run docvault search
            search_op_cls = resolve_op(profile["search"])
            if search_op_cls:
                ctx = await search_op_cls()(ctx)
            else:
                ctx["evidence_chunks"] = []

        # Merge results from both sources
        merge_cls = resolve_op("MergeOp")
        if merge_cls:
            ctx = await merge_cls()(ctx)

        # Rerank merged results
        rerank_op_cls = resolve_op(profile["rerank"])
        if rerank_op_cls:
            ctx = await rerank_op_cls()(ctx)

        # CRAG evaluation
        ctx = await self._evaluate_crag(ctx)

        # If CRAG says INCORRECT, trigger Pipeline B (coverage gap)
        if ctx.get("crag_verdict") == "incorrect":
            await self._trigger_coverage_gap(
                db, request.question, space_id
            )

        # Synthesize
        synth_op_cls = resolve_op(profile["synth"])
        if synth_op_cls:
            ctx = await synth_op_cls()(ctx)
        else:
            ctx["answer"] = "Synthesis operator not available."
            ctx["citations"] = []

        return ctx

    async def _evaluate_crag(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """Evaluate result quality using shared CRAG evaluator."""
        from src.shared.crag_evaluator import evaluate_results

        chunks = ctx.get("evidence_chunks", [])
        question = ctx.get("question", "")

        evaluation = evaluate_results(
            query=question,
            results=chunks,
            score_key="score",
        )
        ctx["crag_verdict"] = evaluation.verdict.value
        ctx["confidence"] = evaluation.confidence_score
        ctx["crag_metadata"] = evaluation.metadata
        return ctx

    async def _trigger_coverage_gap(
        self,
        db: AsyncSession,
        question: str,
        space_id: str,
    ) -> None:
        """Async trigger: emit coverage gap event when CRAG says INCORRECT."""
        import asyncio
        from datetime import UTC, datetime

        from src.events.bus import event_bus
        from src.events.types import DocvaultEvents

        query_hash = _hash_query(question)
        event_data = {
            "query_text": question,
            "query_hash": query_hash,
            "detected_at": datetime.now(UTC).isoformat(),
            "gap_type": "topic_missing",
            "space_id": space_id,
        }
        asyncio.get_running_loop().create_task(
            event_bus.publish(DocvaultEvents.COVERAGE_GAP_DETECTED, event_data)
        )
        logger.info("Coverage gap triggered for query_hash=%s", query_hash[:12])

    async def _record_qa_log(
        self,
        db: AsyncSession,
        *,
        query: str,
        answer: str,
        citations: list[dict],
        confidence: float,
        crag_verdict: str | None,
        pipeline_used: str,
        latency_ms: int,
        space_id: str,
        created_by: str | None,
    ) -> str | None:
        """Record QA execution to QALog table."""
        try:
            from .schemas import QALogCreate
            from .services import qa_log_service

            log_data = QALogCreate(
                query_text=query,
                query_hash=_hash_query(query),
                answer_text=answer,
                citations={"refs": citations},
                confidence=confidence,
                crag_verdict=crag_verdict,
                pipeline_used=pipeline_used,
                latency_ms=latency_ms,
            )
            instance = await qa_log_service.create(db, space_id, log_data)
            return instance.id
        except Exception:
            logger.exception("Failed to record QA log")
            return None


# Module singleton
qa_service = QAService()

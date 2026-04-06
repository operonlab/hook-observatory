"""DocVault GRC Adapter — self-improvement cycle for document quality.

Implements the shared G-R-C (Generate-Reflect-Curate) framework for docvault.

Generate: Gather documents + QA logs + coverage gaps
Reflect:  Analyze quality patterns, low-confidence answers, recurring gaps
Curate:   Propose actions (re-index, archive stale docs, suggest new sources)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.shared.grc import (
    CurateAction,
    CurateResult,
    GenerateItem,
    GRCConfig,
    ReflectResult,
    SupportsCurate,
    SupportsReflect,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class DocvaultGRCAdapter(SupportsReflect, SupportsCurate):
    """GRC adapter for docvault module self-improvement.

    Reflect cycle:
      - Low-confidence QA answers → may indicate poor indexing
      - Recurring coverage gaps → topic blind spots
      - Stale documents (no access in N days) → archive candidates
      - Contradictions → resolution needed

    Curate cycle:
      - Re-index documents with low confidence scores
      - Archive documents with zero access in 90+ days
      - Suggest new sources for recurring gaps
      - Resolve or dismiss old gaps
    """

    MODULE = "docvault"

    def get_config(self) -> GRCConfig:
        return GRCConfig(
            module=self.MODULE,
            reflect_batch_size=50,
            curate_batch_size=20,
            min_items_for_reflect=5,
        )

    async def gather_items(
        self, db: AsyncSession, scope_id: str
    ) -> list[GenerateItem]:
        """Gather documents and QA logs for reflection."""
        from sqlalchemy import select

        from .models import Document, QALog

        items: list[GenerateItem] = []

        # Recent documents
        docs = (
            await db.execute(
                select(Document)
                .where(
                    Document.space_id == scope_id,
                    Document.deleted_at == None,  # noqa: E711
                )
                .order_by(Document.created_at.desc())
                .limit(50)
            )
        ).scalars().all()

        for doc in docs:
            items.append(
                GenerateItem(
                    id=doc.id,
                    content=doc.title,
                    metadata={
                        "type": "document",
                        "status": doc.status,
                        "confidence": doc.confidence,
                        "access_count": doc.access_count,
                        "source_type": doc.source_type,
                        "tags": doc.tags or [],
                        "created_at": doc.created_at.isoformat() if doc.created_at else None,
                        "last_accessed_at": (
                            doc.last_accessed_at.isoformat()
                            if doc.last_accessed_at
                            else None
                        ),
                    },
                )
            )

        # Recent QA logs with low confidence
        qa_logs = (
            await db.execute(
                select(QALog)
                .where(
                    QALog.space_id == scope_id,
                    QALog.deleted_at == None,  # noqa: E711
                )
                .order_by(QALog.created_at.desc())
                .limit(50)
            )
        ).scalars().all()

        for log in qa_logs:
            items.append(
                GenerateItem(
                    id=log.id,
                    content=log.query_text,
                    metadata={
                        "type": "qa_log",
                        "confidence": log.confidence,
                        "crag_verdict": log.crag_verdict,
                        "feedback": log.feedback,
                        "pipeline_used": log.pipeline_used,
                        "latency_ms": log.latency_ms,
                    },
                )
            )

        return items

    async def reflect(
        self, items: list[GenerateItem], scope_id: str
    ) -> ReflectResult:
        """Analyze gathered items for quality patterns."""
        result = ReflectResult(
            module=self.MODULE,
            scope_id=scope_id,
            items_analyzed=len(items),
        )

        docs = [i for i in items if i.metadata.get("type") == "document"]
        qa_logs = [i for i in items if i.metadata.get("type") == "qa_log"]

        # Insight: Low-confidence documents
        low_conf_docs = [
            d for d in docs
            if d.metadata.get("confidence") is not None
            and d.metadata["confidence"] < 0.5
        ]
        if low_conf_docs:
            result.insights.append(
                f"{len(low_conf_docs)} documents have confidence < 0.5 — "
                "consider re-indexing or enriching."
            )

        # Insight: Stale documents (no access)
        stale_docs = [
            d for d in docs
            if d.metadata.get("access_count", 0) == 0
        ]
        if stale_docs:
            result.insights.append(
                f"{len(stale_docs)} documents have never been accessed — "
                "consider archiving or reviewing relevance."
            )

        # Insight: QA quality
        incorrect_qa = [
            q for q in qa_logs
            if q.metadata.get("crag_verdict") == "incorrect"
        ]
        negative_feedback = [
            q for q in qa_logs
            if q.metadata.get("feedback") == "negative"
        ]
        if incorrect_qa:
            result.anomalies.append(
                f"{len(incorrect_qa)} QA answers had INCORRECT verdict — "
                "coverage gaps may need attention."
            )
        if negative_feedback:
            result.anomalies.append(
                f"{len(negative_feedback)} QA answers received negative feedback."
            )

        # Metrics
        total_docs = len(docs)
        result.metrics = {
            "total_documents": total_docs,
            "total_qa_logs": len(qa_logs),
            "low_confidence_ratio": (
                round(len(low_conf_docs) / total_docs, 3) if total_docs else 0.0
            ),
            "incorrect_ratio": (
                round(len(incorrect_qa) / len(qa_logs), 3) if qa_logs else 0.0
            ),
            "stale_ratio": (
                round(len(stale_docs) / total_docs, 3) if total_docs else 0.0
            ),
        }

        return result

    async def curate(
        self, reflect_result: ReflectResult, scope_id: str
    ) -> CurateResult:
        """Propose curation actions based on reflection."""
        actions: list[CurateAction] = []

        # Re-index low confidence
        if reflect_result.metrics.get("low_confidence_ratio", 0) > 0.2:
            actions.append(
                CurateAction(
                    item_id="batch",
                    action="reindex",
                    reason="High proportion of low-confidence documents.",
                    priority=2,
                )
            )

        # Archive stale
        if reflect_result.metrics.get("stale_ratio", 0) > 0.3:
            actions.append(
                CurateAction(
                    item_id="batch",
                    action="archive_stale",
                    reason="Many documents never accessed — consider archiving.",
                    priority=3,
                )
            )

        # Improve coverage
        if reflect_result.metrics.get("incorrect_ratio", 0) > 0.3:
            actions.append(
                CurateAction(
                    item_id="batch",
                    action="expand_coverage",
                    reason="High INCORRECT rate — review coverage gaps.",
                    priority=1,
                )
            )

        return CurateResult(
            module=self.MODULE,
            scope_id=scope_id,
            actions=actions,
            applied=0,
            skipped=0,
        )


# Module singleton
docvault_grc_adapter = DocvaultGRCAdapter()

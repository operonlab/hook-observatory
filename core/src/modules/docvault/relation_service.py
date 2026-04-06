"""DocVault Relation Service — async contradiction detection via events.

Handles:
  1. Reactive relation discovery from QA pipeline contradiction signals
  2. Cross-document contradiction analysis
  3. Temporal invalidation of superseded relations

Design: Read path (QA) does NOT synchronously write KG relations.
Instead, it emits RELATION_DISCOVERED events → this service handles them async.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.events.bus import event_bus
from src.events.types import DocvaultEvents

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class RelationDiscoveryService:
    """Async handler for contradiction detection and relation management.

    Listens to QA pipeline signals and creates DocumentRelation records
    without blocking the read path.
    """

    async def handle_contradiction_signal(
        self,
        db: AsyncSession,
        signal: dict[str, Any],
    ) -> list[str]:
        """Process a contradiction signal from the QA pipeline.

        Args:
            db: Database session.
            signal: Dict with keys:
                - contradictions: list of {chunk_a_id, chunk_b_id, type, ...}
                - space_id: str
                - question: str (the triggering query)

        Returns:
            List of created relation IDs.
        """
        from .schemas import DocumentRelationCreate
        from .services import relation_service

        contradictions = signal.get("contradictions", [])
        space_id = signal.get("space_id", "default")
        created_ids: list[str] = []

        for c in contradictions:
            chunk_a_id = c.get("chunk_a_id", "")
            chunk_b_id = c.get("chunk_b_id", "")
            doc_a_id = c.get("document_a_id", "")
            doc_b_id = c.get("document_b_id", "")

            if not doc_a_id or not doc_b_id:
                # Try to resolve document IDs from chunk IDs
                doc_a_id, doc_b_id = await self._resolve_doc_ids(
                    db, chunk_a_id, chunk_b_id
                )
            if not doc_a_id or not doc_b_id:
                logger.warning(
                    "Cannot resolve doc IDs for chunks %s, %s",
                    chunk_a_id, chunk_b_id,
                )
                continue

            # Skip self-relations
            if doc_a_id == doc_b_id:
                continue

            # Check for existing active relation
            existing = await self._find_active_relation(
                db, doc_a_id, doc_b_id, "contradicts"
            )
            if existing:
                logger.debug(
                    "Contradiction relation already exists: %s ↔ %s",
                    doc_a_id[:8], doc_b_id[:8],
                )
                continue

            try:
                relation_data = DocumentRelationCreate(
                    source_document_id=doc_a_id,
                    target_document_id=doc_b_id,
                    relation_type="contradicts",
                    evidence=c.get("resolution_hint", ""),
                    source_chunk_id=chunk_a_id or None,
                    confidence=c.get("confidence", 0.5),
                )
                instance = await relation_service.create(
                    db, space_id, relation_data
                )
                created_ids.append(instance.id)

                logger.info(
                    "Created contradiction relation: %s ↔ %s (confidence=%.2f)",
                    doc_a_id[:8], doc_b_id[:8],
                    c.get("confidence", 0.5),
                )
            except Exception:
                logger.exception(
                    "Failed to create contradiction relation: %s ↔ %s",
                    doc_a_id[:8], doc_b_id[:8],
                )

        if created_ids:
            await db.commit()

        return created_ids

    async def invalidate_relations(
        self,
        db: AsyncSession,
        document_id: str,
        new_relation_id: str | None = None,
    ) -> int:
        """Invalidate all active relations for a superseded document.

        Called when a document is superseded by a new version.

        Returns:
            Number of relations invalidated.
        """
        from sqlalchemy import update

        from .models import DocumentRelation

        now = datetime.now(UTC)
        stmt = (
            update(DocumentRelation)
            .where(
                (DocumentRelation.source_document_id == document_id)
                | (DocumentRelation.target_document_id == document_id),
                DocumentRelation.invalid_at == None,  # noqa: E711
                DocumentRelation.deleted_at == None,  # noqa: E711
            )
            .values(
                invalid_at=now,
                invalidated_by=new_relation_id,
            )
        )
        result = await db.execute(stmt)
        count = result.rowcount
        if count:
            await db.commit()
            logger.info(
                "Invalidated %d relations for document %s",
                count, document_id[:8],
            )
        return count

    async def find_contradictions(
        self,
        db: AsyncSession,
        document_id: str,
    ) -> list[dict[str, Any]]:
        """Find all active contradiction relations for a document.

        Returns list of dicts with relation details + opposing document info.
        """
        from sqlalchemy import select

        from .models import Document, DocumentRelation

        stmt = (
            select(DocumentRelation)
            .where(
                (DocumentRelation.source_document_id == document_id)
                | (DocumentRelation.target_document_id == document_id),
                DocumentRelation.relation_type == "contradicts",
                DocumentRelation.invalid_at == None,  # noqa: E711
                DocumentRelation.deleted_at == None,  # noqa: E711
            )
            .order_by(DocumentRelation.created_at.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()

        results = []
        for rel in rows:
            other_id = (
                rel.target_document_id
                if rel.source_document_id == document_id
                else rel.source_document_id
            )
            other_doc = (
                await db.execute(
                    select(Document).where(Document.id == other_id)
                )
            ).scalar_one_or_none()

            results.append({
                "relation_id": rel.id,
                "other_document_id": other_id,
                "other_document_title": other_doc.title if other_doc else "Unknown",
                "evidence": rel.evidence,
                "confidence": rel.confidence,
                "source_chunk_id": rel.source_chunk_id,
                "created_at": rel.created_at.isoformat() if rel.created_at else None,
            })

        return results

    async def _resolve_doc_ids(
        self,
        db: AsyncSession,
        chunk_a_id: str,
        chunk_b_id: str,
    ) -> tuple[str, str]:
        """Resolve document IDs from chunk IDs."""
        from sqlalchemy import select

        from .models import DocumentChunk

        doc_a_id = ""
        doc_b_id = ""

        if chunk_a_id:
            row = (
                await db.execute(
                    select(DocumentChunk.document_id).where(
                        DocumentChunk.id == chunk_a_id
                    )
                )
            ).scalar_one_or_none()
            if row:
                doc_a_id = row

        if chunk_b_id:
            row = (
                await db.execute(
                    select(DocumentChunk.document_id).where(
                        DocumentChunk.id == chunk_b_id
                    )
                )
            ).scalar_one_or_none()
            if row:
                doc_b_id = row

        return doc_a_id, doc_b_id

    async def _find_active_relation(
        self,
        db: AsyncSession,
        doc_a_id: str,
        doc_b_id: str,
        relation_type: str,
    ) -> bool:
        """Check if an active relation already exists between two documents."""
        from sqlalchemy import or_, select

        from .models import DocumentRelation

        stmt = select(DocumentRelation.id).where(
            or_(
                (DocumentRelation.source_document_id == doc_a_id)
                & (DocumentRelation.target_document_id == doc_b_id),
                (DocumentRelation.source_document_id == doc_b_id)
                & (DocumentRelation.target_document_id == doc_a_id),
            ),
            DocumentRelation.relation_type == relation_type,
            DocumentRelation.invalid_at == None,  # noqa: E711
            DocumentRelation.deleted_at == None,  # noqa: E711
        )
        return (await db.execute(stmt)).scalar_one_or_none() is not None


# Event handler: wire into event bus
async def _on_relation_discovered(event_data: dict[str, Any]) -> None:
    """Event handler for RELATION_DISCOVERED — creates relation records async."""
    from src.shared.database import async_session_factory

    async with async_session_factory() as db:
        await relation_discovery_service.handle_contradiction_signal(db, event_data)


def register_event_handlers() -> None:
    """Register relation discovery event handlers. Called from events.py."""
    event_bus.subscribe(
        DocvaultEvents.RELATION_DISCOVERED,
        _on_relation_discovered,
    )


# Module singleton
relation_discovery_service = RelationDiscoveryService()

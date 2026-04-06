"""DocVault services — CRUD + version replacement + QA orchestration.

This is the PUBLIC API of the docvault module.
Other modules import from here, never from models.py.
"""

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.errors import NotFoundError
from src.shared.schemas import PaginatedResponse
from src.shared.services import BaseCRUDService

from .events import DocvaultEvents
from .models import (
    CoverageGap,
    Document,
    DocumentChunk,
    DocumentRelation,
    DocumentVersion,
    QALog,
)
from .schemas import (
    CoverageGapCreate,
    CoverageGapResponse,
    CoverageGapUpdate,
    DocumentChunkCreate,
    DocumentChunkResponse,
    DocumentCreate,
    DocumentRelationCreate,
    DocumentRelationResponse,
    DocumentResponse,
    DocumentUpdate,
    DocumentVersionCreate,
    DocumentVersionResponse,
    DocumentVersionUpdate,
    DocvaultStats,
    GapStats,
    QALogCreate,
    QALogResponse,
)

logger = logging.getLogger(__name__)


def _content_hash(content: str) -> str:
    """SHA-256 hash for idempotent upload detection."""
    return hashlib.sha256(content.encode()).hexdigest()


# ======================== DocumentService ========================


class DocumentService(BaseCRUDService[Document, DocumentCreate, DocumentUpdate, DocumentResponse]):
    model = Document
    audit_module = "docvault"
    audit_entity_type = "document"
    event_types = {
        "created": DocvaultEvents.DOCUMENT_CREATED,
        "updated": DocvaultEvents.DOCUMENT_PUBLISHED,
        "deleted": DocvaultEvents.DOCUMENT_ARCHIVED,
    }
    event_fields = ("title", "status", "source_type")

    def to_response(self, instance: Document) -> DocumentResponse:
        return DocumentResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            title=instance.title,
            source_type=instance.source_type,
            source_uri=instance.source_uri,
            content_hash=instance.content_hash,
            current_version_id=instance.current_version_id,
            tags=instance.tags or [],
            metadata=instance.metadata_,
            status=instance.status,
            confidence=instance.confidence,
            access_count=instance.access_count,
            last_accessed_at=instance.last_accessed_at,
        )

    async def list(
        self,
        db: AsyncSession,
        *,
        space_id: str,
        page: int = 1,
        page_size: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> PaginatedResponse[DocumentResponse]:
        """List documents with optional filters."""
        query = select(Document).where(
            Document.space_id == space_id,
            Document.deleted_at.is_(None),
        )
        count_query = select(func.count(Document.id)).where(
            Document.space_id == space_id,
            Document.deleted_at.is_(None),
        )

        if filters:
            if filters.get("status"):
                query = query.where(Document.status == filters["status"])
                count_query = count_query.where(Document.status == filters["status"])
            if filters.get("source_type"):
                query = query.where(Document.source_type == filters["source_type"])
                count_query = count_query.where(Document.source_type == filters["source_type"])
            if filters.get("tag"):
                query = query.where(Document.tags.any(filters["tag"]))
                count_query = count_query.where(Document.tags.any(filters["tag"]))

        total = (await db.execute(count_query)).scalar() or 0
        query = query.order_by(Document.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        items = [self.to_response(row) for row in result.scalars().all()]

        return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)

    async def supersede(
        self,
        db: AsyncSession,
        doc_id: str,
        *,
        raw_content: str,
        content_hash: str,
        space_id: str,
        created_by: str,
    ) -> DocumentVersionResponse:
        """Version replacement flow:

        1. content_hash compare — same → skip (idempotent)
        2. New DocumentVersion (version_number + 1)
        3. Old version status → "superseded"
        4. Old chunks' Qdrant points deleted (via service_id)
        5. New chunks embed + index
        6. Old DocumentRelations: invalid_at = now()
        7. Re-run enrichment pipeline
        8. Emit DOCUMENT_SUPERSEDED event
        """
        doc = await self.get(db, doc_id, space_id=space_id)
        if doc is None:
            raise NotFoundError(f"Document {doc_id} not found")

        # 1. Idempotent check
        if doc.content_hash == content_hash:
            logger.info("Document %s: same content_hash, skip supersede", doc_id)
            current_version = await db.get(DocumentVersion, doc.current_version_id)
            if current_version is None:
                raise NotFoundError(f"Current version for {doc_id} not found")
            return DocumentVersionService().to_response(current_version)

        # 2. Get latest version number
        latest_q = select(func.max(DocumentVersion.version_number)).where(
            DocumentVersion.document_id == doc_id
        )
        latest_num = (await db.execute(latest_q)).scalar() or 0

        # 3. Mark old version as superseded
        if doc.current_version_id:
            await db.execute(
                update(DocumentVersion)
                .where(DocumentVersion.id == doc.current_version_id)
                .values(status="superseded")
            )

        # 4. Create new version
        new_version = DocumentVersion(
            document_id=doc_id,
            version_number=latest_num + 1,
            content_hash=content_hash,
            raw_content=raw_content,
            status="processing",
            space_id=space_id,
            created_by=created_by,
        )
        db.add(new_version)
        await db.flush()

        # 5. Update document pointer + hash
        await db.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(
                current_version_id=new_version.id,
                content_hash=content_hash,
                status="processing",
            )
        )

        # 6. Invalidate old relations
        now = datetime.now(UTC)
        await db.execute(
            update(DocumentRelation)
            .where(
                DocumentRelation.source_document_id == doc_id,
                DocumentRelation.invalid_at.is_(None),
            )
            .values(invalid_at=now)
        )

        await db.commit()

        # 7. Old chunks cleanup + new indexing happens async via event handler
        self._auto_publish_event("superseded", doc)

        logger.info(
            "Document %s superseded: v%d → v%d",
            doc_id,
            latest_num,
            latest_num + 1,
        )
        return DocumentVersionService().to_response(new_version)

    async def stats(self, db: AsyncSession, *, space_id: str) -> DocvaultStats:
        """Aggregate statistics for the docvault module."""
        base_where = [Document.space_id == space_id, Document.deleted_at.is_(None)]

        total_docs = (
            await db.execute(select(func.count(Document.id)).where(*base_where))
        ).scalar() or 0

        total_chunks = (
            await db.execute(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.space_id == space_id,
                    DocumentChunk.deleted_at.is_(None),
                )
            )
        ).scalar() or 0

        total_relations = (
            await db.execute(
                select(func.count(DocumentRelation.id)).where(
                    DocumentRelation.space_id == space_id,
                    DocumentRelation.deleted_at.is_(None),
                )
            )
        ).scalar() or 0

        total_gaps = (
            await db.execute(
                select(func.count(CoverageGap.id)).where(
                    CoverageGap.space_id == space_id,
                    CoverageGap.deleted_at.is_(None),
                )
            )
        ).scalar() or 0

        total_qa = (
            await db.execute(
                select(func.count(QALog.id)).where(
                    QALog.space_id == space_id,
                    QALog.deleted_at.is_(None),
                )
            )
        ).scalar() or 0

        # Status breakdown
        status_q = (
            select(Document.status, func.count(Document.id))
            .where(*base_where)
            .group_by(Document.status)
        )
        by_status = dict((await db.execute(status_q)).all())

        # Source type breakdown
        type_q = (
            select(Document.source_type, func.count(Document.id))
            .where(*base_where)
            .group_by(Document.source_type)
        )
        by_source_type = dict((await db.execute(type_q)).all())

        return DocvaultStats(
            total_documents=total_docs,
            total_chunks=total_chunks,
            total_relations=total_relations,
            total_gaps=total_gaps,
            total_qa_logs=total_qa,
            by_status=by_status,
            by_source_type=by_source_type,
        )

    async def reindex(self, db: AsyncSession, doc_id: str, *, space_id: str) -> None:
        """Queue a document for re-indexing."""
        doc = await self.get(db, doc_id, space_id=space_id)
        if doc is None:
            raise NotFoundError(f"Document {doc_id} not found")
        await db.execute(update(Document).where(Document.id == doc_id).values(status="processing"))
        await db.commit()
        # Event triggers async re-indexing pipeline
        self._auto_publish_event("updated", doc)


# ======================== DocumentVersionService ========================


class DocumentVersionService(
    BaseCRUDService[
        DocumentVersion, DocumentVersionCreate, DocumentVersionUpdate, DocumentVersionResponse
    ]
):
    model = DocumentVersion
    audit_module = "docvault"
    audit_entity_type = "document_version"

    def to_response(self, instance: DocumentVersion) -> DocumentVersionResponse:
        return DocumentVersionResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            document_id=instance.document_id,
            version_number=instance.version_number,
            content_hash=instance.content_hash,
            status=instance.status,
            chunk_count=instance.chunk_count,
            extraction_model=instance.extraction_model,
            summary=instance.summary,
            table_of_contents=instance.table_of_contents,
        )

    async def list_by_document(
        self,
        db: AsyncSession,
        doc_id: str,
        *,
        space_id: str,
    ) -> list[DocumentVersionResponse]:
        query = (
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == doc_id,
                DocumentVersion.space_id == space_id,
                DocumentVersion.deleted_at.is_(None),
            )
            .order_by(DocumentVersion.version_number.desc())
        )
        result = await db.execute(query)
        return [self.to_response(v) for v in result.scalars().all()]


# ======================== ChunkService ========================


class ChunkService(
    BaseCRUDService[
        DocumentChunk, DocumentChunkCreate, DocumentChunkResponse, DocumentChunkResponse
    ]
):
    model = DocumentChunk
    audit_module = "docvault"
    audit_entity_type = "chunk"

    def to_response(self, instance: DocumentChunk) -> DocumentChunkResponse:
        return DocumentChunkResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            version_id=instance.version_id,
            document_id=instance.document_id,
            chunk_index=instance.chunk_index,
            content=instance.content,
            section_path=instance.section_path,
            page_range=instance.page_range,
            heading=instance.heading,
            token_count=instance.token_count,
            chunk_type=instance.chunk_type,
        )

    async def delete_by_version(self, db: AsyncSession, version_id: str) -> int:
        """Soft-delete all chunks for a given version. Returns count deleted."""
        now = datetime.now(UTC)
        result = await db.execute(
            update(DocumentChunk)
            .where(
                DocumentChunk.version_id == version_id,
                DocumentChunk.deleted_at.is_(None),
            )
            .values(deleted_at=now)
        )
        return result.rowcount


# ======================== RelationService ========================


class RelationService(
    BaseCRUDService[
        DocumentRelation,
        DocumentRelationCreate,
        DocumentRelationResponse,
        DocumentRelationResponse,
    ]
):
    model = DocumentRelation
    audit_module = "docvault"
    audit_entity_type = "relation"

    def to_response(self, instance: DocumentRelation) -> DocumentRelationResponse:
        return DocumentRelationResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            source_document_id=instance.source_document_id,
            target_document_id=instance.target_document_id,
            relation_type=instance.relation_type,
            evidence=instance.evidence,
            source_chunk_id=instance.source_chunk_id,
            confidence=instance.confidence,
            valid_from=instance.valid_from,
            invalid_at=instance.invalid_at,
            invalidated_by=instance.invalidated_by,
        )

    async def list_by_document(
        self,
        db: AsyncSession,
        doc_id: str,
        *,
        space_id: str,
    ) -> list[DocumentRelationResponse]:
        query = (
            select(DocumentRelation)
            .where(
                (DocumentRelation.source_document_id == doc_id)
                | (DocumentRelation.target_document_id == doc_id),
                DocumentRelation.space_id == space_id,
                DocumentRelation.deleted_at.is_(None),
                DocumentRelation.invalid_at.is_(None),
            )
            .order_by(DocumentRelation.created_at.desc())
        )
        result = await db.execute(query)
        return [self.to_response(r) for r in result.scalars().all()]


# ======================== CoverageGapService ========================


class CoverageGapService(
    BaseCRUDService[CoverageGap, CoverageGapCreate, CoverageGapUpdate, CoverageGapResponse]
):
    model = CoverageGap
    audit_module = "docvault"
    audit_entity_type = "coverage_gap"
    event_types = {
        "created": DocvaultEvents.COVERAGE_GAP_DETECTED,
        "updated": DocvaultEvents.COVERAGE_GAP_RESOLVED,
    }

    def to_response(self, instance: CoverageGap) -> CoverageGapResponse:
        return CoverageGapResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            query_text=instance.query_text,
            query_hash=instance.query_hash,
            detected_at=instance.detected_at,
            gap_type=instance.gap_type,
            status=instance.status,
            resolution=instance.resolution,
            resolved_document_id=instance.resolved_document_id,
            suggested_sources=instance.suggested_sources,
        )

    async def list(
        self,
        db: AsyncSession,
        *,
        space_id: str,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
    ) -> PaginatedResponse[CoverageGapResponse]:
        where_clauses = [
            CoverageGap.space_id == space_id,
            CoverageGap.deleted_at.is_(None),
        ]
        if status:
            where_clauses.append(CoverageGap.status == status)

        total = (
            await db.execute(select(func.count(CoverageGap.id)).where(*where_clauses))
        ).scalar() or 0

        query = (
            select(CoverageGap)
            .where(*where_clauses)
            .order_by(CoverageGap.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(query)
        items = [self.to_response(g) for g in result.scalars().all()]

        return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)

    async def stats(self, db: AsyncSession, *, space_id: str) -> GapStats:
        base = [CoverageGap.space_id == space_id, CoverageGap.deleted_at.is_(None)]
        total = (await db.execute(select(func.count(CoverageGap.id)).where(*base))).scalar() or 0

        status_q = (
            select(CoverageGap.status, func.count(CoverageGap.id))
            .where(*base)
            .group_by(CoverageGap.status)
        )
        counts = dict((await db.execute(status_q)).all())

        return GapStats(
            total=total,
            pending=counts.get("pending", 0),
            investigating=counts.get("investigating", 0),
            resolved=counts.get("resolved", 0),
            dismissed=counts.get("dismissed", 0),
        )


# ======================== QALogService ========================


class QALogService(BaseCRUDService[QALog, QALogCreate, QALogResponse, QALogResponse]):
    model = QALog
    audit_module = "docvault"
    audit_entity_type = "qa_log"
    event_types = {
        "created": DocvaultEvents.QA_EXECUTED,
    }

    def to_response(self, instance: QALog) -> QALogResponse:
        return QALogResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_by=instance.created_by,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            query_text=instance.query_text,
            query_hash=instance.query_hash,
            answer_text=instance.answer_text,
            citations=instance.citations,
            confidence=instance.confidence,
            crag_verdict=instance.crag_verdict,
            feedback=instance.feedback,
            pipeline_used=instance.pipeline_used,
            latency_ms=instance.latency_ms,
        )

    async def list(
        self,
        db: AsyncSession,
        *,
        space_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> PaginatedResponse[QALogResponse]:
        where_clauses = [QALog.space_id == space_id, QALog.deleted_at.is_(None)]
        total = (await db.execute(select(func.count(QALog.id)).where(*where_clauses))).scalar() or 0

        query = (
            select(QALog)
            .where(*where_clauses)
            .order_by(QALog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(query)
        items = [self.to_response(log) for log in result.scalars().all()]

        return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)

    async def set_feedback(
        self,
        db: AsyncSession,
        qa_log_id: str,
        feedback: str,
        *,
        space_id: str,
    ) -> QALogResponse:
        """Set user feedback on a QA log entry."""
        log = await db.get(QALog, qa_log_id)
        if log is None or log.space_id != space_id:
            raise NotFoundError(f"QA log {qa_log_id} not found")
        log.feedback = feedback
        await db.commit()
        await db.refresh(log)
        self._auto_publish_event("feedback", log)
        return self.to_response(log)

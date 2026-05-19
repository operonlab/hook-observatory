"""DocVault services — CRUD + domain logic.

This is the PUBLIC API of the docvault module.
Other modules import from here, never from models.py.
"""

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.types import DocvaultEvents
from src.shared.cache import cached
from src.shared.schemas import PaginatedResponse, PaginationParams
from src.shared.services import BaseCRUDService

from .models import (
    CoverageGap,
    Document,
    DocumentChunk,
    DocumentRelation,
    DocumentVersion,
    PreGeneratedQA,
    QALog,
)
from .schemas import (
    CoverageGapCreate,
    CoverageGapResponse,
    CoverageGapUpdate,
    DocumentBrief,
    DocumentChunkCreate,
    DocumentChunkResponse,
    DocumentCreate,
    DocumentRelationCreate,
    DocumentRelationResponse,
    DocumentRelationUpdate,
    DocumentResponse,
    DocumentUpdate,
    DocumentVersionCreate,
    DocumentVersionResponse,
    DocumentVersionUpdate,
    DocvaultDashboardResponse,
    PreGeneratedQAResponse,
    QALogCreate,
    QALogResponse,
)

logger = logging.getLogger(__name__)


# ======================== Document Service ========================


class DocumentService(
    BaseCRUDService[Document, DocumentCreate, DocumentUpdate, DocumentResponse]
):
    model = Document
    audit_module = "docvault"
    audit_entity_type = "documents"
    event_types = {
        "created": DocvaultEvents.DOCUMENT_CREATED,
        "updated": DocvaultEvents.DOCUMENT_ENRICHED,
        "deleted": DocvaultEvents.DOCUMENT_ARCHIVED,
    }
    event_id_alias = "document_id"
    event_fields = ("title", "source_type", "status", "tags", "content_hash")

    def before_create(self, data: DocumentCreate, **kwargs: Any) -> dict:
        d = data.model_dump(by_alias=True)
        # Remap alias back to column name
        if "metadata" in d:
            d["metadata_"] = d.pop("metadata")
        return d

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

    def to_brief(self, instance: Document) -> DocumentBrief:
        return DocumentBrief(
            id=instance.id,
            title=instance.title,
            source_type=instance.source_type,
            tags=instance.tags or [],
            status=instance.status,
            created_at=instance.created_at,
        )

    async def get_by_content_hash(
        self, db: AsyncSession, content_hash: str, space_id: str
    ) -> Document | None:
        """Dedup check by content hash, scoped to a single space."""
        q = select(Document).where(
            Document.content_hash == content_hash,
            Document.space_id == space_id,
            Document.deleted_at == None,  # noqa: E711
        )
        return (await db.execute(q)).scalar_one_or_none()


# ======================== DocumentVersion Service ========================


class DocumentVersionService(
    BaseCRUDService[
        DocumentVersion,
        DocumentVersionCreate,
        DocumentVersionUpdate,
        DocumentVersionResponse,
    ]
):
    model = DocumentVersion
    audit_module = "docvault"
    audit_entity_type = "document_versions"

    def before_create(self, data: DocumentVersionCreate, **kwargs: Any) -> dict:
        return data.model_dump()

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
        document_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[DocumentVersionResponse]:
        p = pagination or PaginationParams()
        base = select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.deleted_at == None,  # noqa: E711
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = (
            base.order_by(DocumentVersion.version_number.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[DocumentVersionResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


# ======================== Chunk Service ========================


class ChunkService(
    BaseCRUDService[
        DocumentChunk, DocumentChunkCreate, DocumentChunkCreate, DocumentChunkResponse
    ]
):
    model = DocumentChunk
    audit_module = "docvault"
    audit_entity_type = "document_chunks"

    def before_create(self, data: DocumentChunkCreate, **kwargs: Any) -> dict:
        return data.model_dump()

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
            source_role=instance.source_role,
            doc_weight=instance.doc_weight,
        )

    async def list_by_version(
        self,
        db: AsyncSession,
        version_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[DocumentChunkResponse]:
        p = pagination or PaginationParams()
        base = select(DocumentChunk).where(
            DocumentChunk.version_id == version_id,
            DocumentChunk.deleted_at == None,  # noqa: E711
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = (
            base.order_by(DocumentChunk.chunk_index.asc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[DocumentChunkResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )

    async def list_by_document(
        self,
        db: AsyncSession,
        document_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[DocumentChunkResponse]:
        p = pagination or PaginationParams()
        base = select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.deleted_at == None,  # noqa: E711
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = (
            base.order_by(DocumentChunk.chunk_index.asc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[DocumentChunkResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


# ======================== Relation Service ========================


class RelationService(
    BaseCRUDService[
        DocumentRelation,
        DocumentRelationCreate,
        DocumentRelationUpdate,
        DocumentRelationResponse,
    ]
):
    model = DocumentRelation
    audit_module = "docvault"
    audit_entity_type = "document_relations"
    event_types = {"created": DocvaultEvents.RELATION_DISCOVERED}
    event_fields = (
        "source_document_id",
        "target_document_id",
        "relation_type",
        "confidence",
    )

    def before_create(self, data: DocumentRelationCreate, **kwargs: Any) -> dict:
        return data.model_dump()

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
        document_id: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[DocumentRelationResponse]:
        p = pagination or PaginationParams()
        base = select(DocumentRelation).where(
            (DocumentRelation.source_document_id == document_id)
            | (DocumentRelation.target_document_id == document_id),
            DocumentRelation.deleted_at == None,  # noqa: E711
            DocumentRelation.invalid_at == None,  # noqa: E711
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = (
            base.order_by(DocumentRelation.created_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[DocumentRelationResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


# ======================== CoverageGap Service ========================


class CoverageGapService(
    BaseCRUDService[CoverageGap, CoverageGapCreate, CoverageGapUpdate, CoverageGapResponse]
):
    model = CoverageGap
    audit_module = "docvault"
    audit_entity_type = "coverage_gaps"
    event_types = {
        "created": DocvaultEvents.COVERAGE_GAP_DETECTED,
    }
    event_fields = ("query_hash", "gap_type", "status")

    def before_create(self, data: CoverageGapCreate, **kwargs: Any) -> dict:
        return data.model_dump()

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

    async def list_by_status(
        self,
        db: AsyncSession,
        space_id: str,
        status: str,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResponse[CoverageGapResponse]:
        p = pagination or PaginationParams()
        base = select(CoverageGap).where(
            CoverageGap.space_id == space_id,
            CoverageGap.status == status,
            CoverageGap.deleted_at == None,  # noqa: E711
        )
        count_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_q)).scalar_one()
        q = (
            base.order_by(CoverageGap.detected_at.desc())
            .offset((p.page - 1) * p.page_size)
            .limit(p.page_size)
        )
        rows = (await db.execute(q)).scalars().all()
        return PaginatedResponse[CoverageGapResponse](
            items=[self.to_response(r) for r in rows],
            total=total,
            page=p.page,
            page_size=p.page_size,
        )


# ======================== QALog Service ========================


class QALogService(
    BaseCRUDService[QALog, QALogCreate, QALogCreate, QALogResponse]
):
    model = QALog
    audit_module = "docvault"
    audit_entity_type = "qa_logs"
    event_types = {"created": DocvaultEvents.QA_EXECUTED}
    event_fields = ("query_hash", "crag_verdict", "pipeline_used", "confidence")

    def before_create(self, data: QALogCreate, **kwargs: Any) -> dict:
        return data.model_dump()

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

    async def record_feedback(
        self, db: AsyncSession, qa_log_id: str, feedback: str
    ) -> QALog | None:
        """Record user feedback on a QA result."""
        instance = await self.get(db, qa_log_id)
        if not instance:
            return None
        instance.feedback = feedback
        await db.flush()
        return instance


# ======================== Dashboard Service ========================


class DashboardService:
    """Statistics and summary for the docvault module."""

    @cached("docvault", "dashboard_summary", ttl=3600, key_params=("space_id",))
    async def get_summary(
        self, db: AsyncSession, space_id: str
    ) -> DocvaultDashboardResponse:
        stats_q = select(
            select(func.count())
            .select_from(Document)
            .where(Document.space_id == space_id, Document.deleted_at == None)  # noqa: E711
            .correlate(None)
            .scalar_subquery()
            .label("total_documents"),
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.space_id == space_id,
                DocumentChunk.deleted_at == None,  # noqa: E711
            )
            .correlate(None)
            .scalar_subquery()
            .label("total_chunks"),
            select(func.count())
            .select_from(QALog)
            .where(QALog.space_id == space_id, QALog.deleted_at == None)  # noqa: E711
            .correlate(None)
            .scalar_subquery()
            .label("total_qa_logs"),
            select(func.count())
            .select_from(CoverageGap)
            .where(
                CoverageGap.space_id == space_id,
                CoverageGap.status == "pending",
                CoverageGap.deleted_at == None,  # noqa: E711
            )
            .correlate(None)
            .scalar_subquery()
            .label("coverage_gap_count"),
            select(func.count())
            .select_from(Document)
            .where(
                Document.space_id == space_id,
                Document.status == "published",
                Document.deleted_at == None,  # noqa: E711
            )
            .correlate(None)
            .scalar_subquery()
            .label("published_count"),
        )
        stats = (await db.execute(stats_q)).one()

        recent_rows = (
            (
                await db.execute(
                    select(Document)
                    .where(
                        Document.space_id == space_id,
                        Document.deleted_at == None,  # noqa: E711
                    )
                    .order_by(Document.created_at.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        recent_documents = [
            DocumentBrief(
                id=d.id,
                title=d.title,
                source_type=d.source_type,
                tags=d.tags or [],
                status=d.status,
                created_at=d.created_at,
            )
            for d in recent_rows
        ]

        return DocvaultDashboardResponse(
            total_documents=stats.total_documents,
            total_chunks=stats.total_chunks,
            total_qa_logs=stats.total_qa_logs,
            coverage_gap_count=stats.coverage_gap_count,
            published_count=stats.published_count,
            recent_documents=recent_documents,
        )


# ======================== PreGeneratedQA Service ========================


class PreGeneratedQAService(
    BaseCRUDService[PreGeneratedQA, None, None, PreGeneratedQAResponse]
):
    model = PreGeneratedQA
    audit_module = "docvault"
    audit_entity_type = "pre_generated_qa"

    def to_response(self, instance: PreGeneratedQA) -> PreGeneratedQAResponse:
        return PreGeneratedQAResponse(
            id=instance.id,
            space_id=instance.space_id,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            document_id=instance.document_id,
            version_id=instance.version_id,
            question=instance.question,
            answer=instance.answer,
            question_type=instance.question_type,
            source_chunks=instance.source_chunks,
            confidence=instance.confidence,
            status=instance.status,
            reuse_count=instance.reuse_count,
        )


# ======================== Module-level singletons ========================

document_service = DocumentService()
version_service = DocumentVersionService()
chunk_service = ChunkService()
relation_service = RelationService()
coverage_gap_service = CoverageGapService()
qa_log_service = QALogService()
pre_generated_qa_service = PreGeneratedQAService()
dashboard_service = DashboardService()

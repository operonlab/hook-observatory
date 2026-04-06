"""DocVault FastAPI dependencies."""

from .services import (
    ChunkService,
    CoverageGapService,
    DocumentService,
    DocumentVersionService,
    QALogService,
    RelationService,
)

document_service = DocumentService()
version_service = DocumentVersionService()
chunk_service = ChunkService()
relation_service = RelationService()
coverage_service = CoverageGapService()
qa_log_service = QALogService()

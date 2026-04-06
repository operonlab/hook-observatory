"""DocVault service tests — service instantiation, schema validation, domain profiles."""

import pytest

from ..domain_profiles import (
    DOMAIN_PROFILES,
    get_profile,
    list_profiles,
    resolve_op,
)
from ..schemas import (
    DocumentCreate,
    DocumentUpdate,
    QARequest,
    QAResponse,
)
from ..services import (
    chunk_service,
    coverage_gap_service,
    dashboard_service,
    document_service,
    qa_log_service,
    relation_service,
    version_service,
)

# ======================== Service Singletons ========================


class TestServiceInstantiation:
    def test_document_service_exists(self):
        assert document_service is not None
        assert document_service.model.__tablename__ == "documents"

    def test_version_service_exists(self):
        assert version_service is not None
        assert version_service.model.__tablename__ == "document_versions"

    def test_chunk_service_exists(self):
        assert chunk_service is not None
        assert chunk_service.model.__tablename__ == "document_chunks"

    def test_relation_service_exists(self):
        assert relation_service is not None
        assert relation_service.model.__tablename__ == "document_relations"

    def test_coverage_gap_service_exists(self):
        assert coverage_gap_service is not None

    def test_qa_log_service_exists(self):
        assert qa_log_service is not None

    def test_dashboard_service_exists(self):
        assert dashboard_service is not None


# ======================== Schema Validation ========================


class TestSchemaValidation:
    def test_document_create_minimal(self):
        doc = DocumentCreate(title="Test Doc", content_hash="a" * 64)
        assert doc.title == "Test Doc"
        assert doc.source_type == "markdown"

    def test_document_create_with_tags(self):
        doc = DocumentCreate(
            title="Legal Brief",
            content_hash="b" * 64,
            source_type="pdf",
            tags=["legal", "contract"],
        )
        assert doc.tags == ["legal", "contract"]
        assert doc.source_type == "pdf"

    def test_document_create_invalid_source_type(self):
        with pytest.raises(ValueError):
            DocumentCreate(
                title="Bad", content_hash="c" * 64, source_type="invalid"
            )

    def test_document_update_partial(self):
        update = DocumentUpdate(title="Updated Title")
        assert update.title == "Updated Title"
        assert update.tags is None
        assert update.status is None

    def test_qa_request_defaults(self):
        req = QARequest(question="What is X?")
        assert req.mode == "factual"
        assert req.domain == "default"
        assert req.top_k == 6

    def test_qa_request_custom(self):
        req = QARequest(
            question="Legal question",
            mode="mixed",
            domain="legal",
            top_k=10,
        )
        assert req.mode == "mixed"
        assert req.domain == "legal"

    def test_qa_response_structure(self):
        resp = QAResponse(
            question="Test?",
            answer="Answer.",
            citations=[],
            confidence=0.9,
            pipeline_used="A",
        )
        assert resp.confidence == 0.9


# ======================== Domain Profiles ========================


class TestDomainProfiles:
    def test_default_profile_exists(self):
        profile = get_profile("default")
        assert "chunk" in profile
        assert "index" in profile
        assert "search" in profile
        assert "rerank" in profile
        assert "synth" in profile

    def test_legal_profile(self):
        profile = get_profile("legal")
        assert profile["chunk"] == "HierarchicalChunkOp"
        assert profile["synth"] == "ContradictionAwareOp"

    def test_medical_profile(self):
        profile = get_profile("medical")
        assert profile["synth"] == "StrictCiteOp"

    def test_finance_profile(self):
        assert "finance" in DOMAIN_PROFILES
        assert get_profile("finance") is not None

    def test_unknown_domain_falls_back(self):
        profile = get_profile("unknown_domain")
        default = get_profile("default")
        assert profile == default

    def test_all_profiles_have_5_slots(self):
        for name, profile in DOMAIN_PROFILES.items():
            assert len(profile) == 5, f"Profile '{name}' has {len(profile)} slots, expected 5"

    def test_list_profiles(self):
        profiles = list_profiles()
        assert len(profiles) >= 4
        names = [p["domain"] for p in profiles]
        assert "default" in names
        assert "legal" in names
        assert "medical" in names
        assert "finance" in names

    def test_resolve_implemented_ops(self):
        assert resolve_op("HierarchicalChunkOp") is not None
        assert resolve_op("StrictCiteOp") is not None
        assert resolve_op("ContradictionAwareOp") is not None

    def test_resolve_unimplemented_returns_none(self):
        assert resolve_op("RAPTORIndexOp") is None
        assert resolve_op("NonexistentOp") is None

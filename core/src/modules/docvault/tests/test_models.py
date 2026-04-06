"""DocVault model tests — schema validation, constraints, FSM transitions."""

import pytest

from ..lifecycle import (
    DOCUMENT_STATES,
    DOCUMENT_TRANSITIONS,
    VERSION_STATES,
    can_transition_document,
    can_transition_version,
    validate_document_transition,
    validate_version_transition,
)
from ..models import (
    SCHEMA,
    CoverageGap,
    Document,
    DocumentChunk,
    DocumentRelation,
    DocumentVersion,
    QALog,
)

# ======================== Schema & Table Names ========================


class TestSchemaDefinition:
    def test_schema_name(self):
        assert SCHEMA == "docvault"

    def test_document_tablename(self):
        assert Document.__tablename__ == "documents"

    def test_version_tablename(self):
        assert DocumentVersion.__tablename__ == "document_versions"

    def test_chunk_tablename(self):
        assert DocumentChunk.__tablename__ == "document_chunks"

    def test_relation_tablename(self):
        assert DocumentRelation.__tablename__ == "document_relations"

    def test_coverage_gap_tablename(self):
        assert CoverageGap.__tablename__ == "coverage_gaps"

    def test_qa_log_tablename(self):
        assert QALog.__tablename__ == "qa_logs"

    def test_all_models_in_correct_schema(self):
        """All docvault models must live in the 'docvault' schema."""
        models = [Document, DocumentVersion, DocumentChunk,
                  DocumentRelation, CoverageGap, QALog]
        for model in models:
            schema = None
            for arg in model.__table_args__:
                if isinstance(arg, dict) and "schema" in arg:
                    schema = arg["schema"]
            assert schema == "docvault", f"{model.__name__} not in docvault schema"


# ======================== Document Lifecycle FSM ========================


class TestDocumentLifecycle:
    def test_all_states_defined(self):
        expected = {"ingested", "processing", "indexed", "enriched",
                    "published", "archived", "failed"}
        assert DOCUMENT_STATES == expected

    def test_valid_transitions(self):
        assert can_transition_document("ingested", "processing")
        assert can_transition_document("processing", "indexed")
        assert can_transition_document("indexed", "enriched")
        assert can_transition_document("enriched", "published")
        assert can_transition_document("published", "archived")

    def test_failure_transitions(self):
        for state in ("ingested", "processing", "indexed"):
            assert can_transition_document(state, "failed")

    def test_invalid_transitions(self):
        assert not can_transition_document("published", "ingested")
        assert not can_transition_document("archived", "processing")
        assert not can_transition_document("failed", "processing")

    def test_terminal_states(self):
        for state in ("archived", "failed"):
            assert DOCUMENT_TRANSITIONS[state] == set()

    def test_validate_raises_on_invalid(self):
        with pytest.raises(ValueError, match="Invalid document transition"):
            validate_document_transition("archived", "processing")

    def test_validate_passes_on_valid(self):
        validate_document_transition("ingested", "processing")


# ======================== Version Lifecycle FSM ========================


class TestVersionLifecycle:
    def test_all_states_defined(self):
        assert VERSION_STATES == {"processing", "ready", "superseded"}

    def test_valid_transitions(self):
        assert can_transition_version("processing", "ready")
        assert can_transition_version("ready", "superseded")

    def test_invalid_transitions(self):
        assert not can_transition_version("superseded", "processing")
        assert not can_transition_version("ready", "processing")

    def test_validate_raises_on_invalid(self):
        with pytest.raises(ValueError, match="Invalid version transition"):
            validate_version_transition("superseded", "ready")

    def test_validate_passes_on_valid(self):
        validate_version_transition("processing", "ready")


# ======================== Model Field Presence ========================


class TestModelFields:
    def test_document_has_required_fields(self):
        columns = {c.name for c in Document.__table__.columns}
        required = {"id", "title", "source_type", "content_hash", "status",
                     "tags", "space_id", "created_at", "updated_at"}
        assert required.issubset(columns), f"Missing: {required - columns}"

    def test_chunk_has_section_path(self):
        columns = {c.name for c in DocumentChunk.__table__.columns}
        assert "section_path" in columns
        assert "heading" in columns
        assert "chunk_type" in columns

    def test_relation_has_temporal_fields(self):
        columns = {c.name for c in DocumentRelation.__table__.columns}
        assert "valid_from" in columns
        assert "invalid_at" in columns
        assert "invalidated_by" in columns

    def test_coverage_gap_has_hash(self):
        columns = {c.name for c in CoverageGap.__table__.columns}
        assert "query_hash" in columns
        assert "gap_type" in columns

    def test_qa_log_has_pipeline_used(self):
        columns = {c.name for c in QALog.__table__.columns}
        assert "pipeline_used" in columns
        assert "crag_verdict" in columns
        assert "latency_ms" in columns

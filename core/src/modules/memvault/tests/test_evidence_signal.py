"""Unit tests for evidence_signal helper.

Tests pure mapping function — no DB / no I/O.
"""

import pytest

from src.modules.memvault.crag_evaluator import (
    EVIDENCE_SIGNAL_AMBIGUOUS_THRESHOLD,
    EVIDENCE_SIGNAL_EXTRACTED_THRESHOLD,
    signal_from_score,
)


class TestSignalFromScore:
    def test_none_defaults_to_extracted(self):
        assert signal_from_score(None) == "extracted"

    def test_high_confidence_is_extracted(self):
        assert signal_from_score(1.0) == "extracted"
        assert signal_from_score(0.95) == "extracted"
        assert signal_from_score(EVIDENCE_SIGNAL_EXTRACTED_THRESHOLD) == "extracted"

    def test_mid_confidence_is_inferred(self):
        assert signal_from_score(0.7) == "inferred"
        assert signal_from_score(0.5) == "inferred"
        assert signal_from_score(EVIDENCE_SIGNAL_AMBIGUOUS_THRESHOLD) == "inferred"

    def test_low_confidence_is_ambiguous(self):
        assert signal_from_score(0.0) == "ambiguous"
        assert signal_from_score(0.1) == "ambiguous"
        assert signal_from_score(EVIDENCE_SIGNAL_AMBIGUOUS_THRESHOLD - 0.001) == "ambiguous"

    def test_boundary_extracted_inclusive(self):
        """Boundary value 0.8 maps to extracted (inclusive)."""
        assert signal_from_score(EVIDENCE_SIGNAL_EXTRACTED_THRESHOLD) == "extracted"
        assert signal_from_score(EVIDENCE_SIGNAL_EXTRACTED_THRESHOLD - 0.001) == "inferred"

    def test_boundary_ambiguous_exclusive(self):
        """Boundary value 0.4 maps to inferred (ambiguous is < 0.4, exclusive)."""
        assert signal_from_score(EVIDENCE_SIGNAL_AMBIGUOUS_THRESHOLD) == "inferred"
        assert signal_from_score(EVIDENCE_SIGNAL_AMBIGUOUS_THRESHOLD - 0.001) == "ambiguous"


class TestEvidenceSignalSchema:
    def test_triple_create_default_evidence_signal(self):
        from src.modules.memvault.kg_schemas import TripleCreate

        triple = TripleCreate(subject="s", predicate="p", object="o")
        assert triple.evidence_signal == "extracted"
        assert triple.evidence_method is None

    def test_triple_create_explicit_signal(self):
        from src.modules.memvault.kg_schemas import TripleCreate

        triple = TripleCreate(
            subject="s",
            predicate="p",
            object="o",
            evidence_signal="inferred",
            evidence_method="llm-extraction",
        )
        assert triple.evidence_signal == "inferred"
        assert triple.evidence_method == "llm-extraction"

    def test_triple_create_invalid_signal_rejected(self):
        from pydantic import ValidationError

        from src.modules.memvault.kg_schemas import TripleCreate

        with pytest.raises(ValidationError):
            TripleCreate(
                subject="s",
                predicate="p",
                object="o",
                evidence_signal="not_a_valid_tier",  # type: ignore[arg-type]
            )


class TestCitationConfidenceSchema:
    def test_citation_ref_default_no_confidence(self):
        from src.modules.docvault.schemas import CitationRef

        cite = CitationRef(document_id="doc-1")
        assert cite.confidence is None
        assert cite.confidence_type is None

    def test_citation_ref_full(self):
        from src.modules.docvault.schemas import CitationRef

        cite = CitationRef(
            document_id="doc-1",
            chunk_id="ch-1",
            quote="hello",
            confidence=0.85,
            confidence_type="extracted",
        )
        assert cite.confidence == 0.85
        assert cite.confidence_type == "extracted"

    def test_citation_ref_confidence_range_validated(self):
        from pydantic import ValidationError

        from src.modules.docvault.schemas import CitationRef

        with pytest.raises(ValidationError):
            CitationRef(document_id="doc-1", confidence=1.5)
        with pytest.raises(ValidationError):
            CitationRef(document_id="doc-1", confidence=-0.1)

"""Phase B 六鐵律 — 鐵律 5 (Adversary Edges) + 鐵律 6 (Regression).

合一檔，cover evidence_signal 異常輸入與既有功能不退化。
"""

from __future__ import annotations

import math

import pytest


# ============================================================================
# 鐵律 5 — Adversary Edge Cases
# ============================================================================


class TestSignalFromScoreEdges:
    """signal_from_score 對異常輸入不 crash."""

    def test_nan_returns_valid_string(self):
        from src.modules.memvault.crag_evaluator import signal_from_score

        # NaN > 0.8 is False, NaN < 0.4 is False → falls through to 'inferred'
        result = signal_from_score(float("nan"))
        assert result in ("extracted", "inferred", "ambiguous")

    def test_negative_infinity_is_ambiguous(self):
        from src.modules.memvault.crag_evaluator import signal_from_score

        assert signal_from_score(float("-inf")) == "ambiguous"

    def test_positive_infinity_is_extracted(self):
        from src.modules.memvault.crag_evaluator import signal_from_score

        assert signal_from_score(float("inf")) == "extracted"

    def test_negative_score_is_ambiguous(self):
        from src.modules.memvault.crag_evaluator import signal_from_score

        assert signal_from_score(-1.0) == "ambiguous"
        assert signal_from_score(-100.0) == "ambiguous"

    def test_above_one_is_extracted(self):
        from src.modules.memvault.crag_evaluator import signal_from_score

        assert signal_from_score(2.0) == "extracted"
        assert signal_from_score(100.0) == "extracted"


class TestTripleCreateValidation:
    """Pydantic validation rejects bad evidence_signal / evidence_method."""

    def test_invalid_signal_rejected(self):
        from pydantic import ValidationError

        from src.modules.memvault.kg_schemas import TripleCreate

        with pytest.raises(ValidationError):
            TripleCreate(
                subject="s",
                predicate="p",
                object="o",
                evidence_signal="garbage_value",  # type: ignore[arg-type]
            )

    def test_evidence_method_max_length(self):
        from pydantic import ValidationError

        from src.modules.memvault.kg_schemas import TripleCreate

        # max_length=32
        with pytest.raises(ValidationError):
            TripleCreate(
                subject="s",
                predicate="p",
                object="o",
                evidence_method="x" * 33,
            )

    def test_evidence_method_at_max_length(self):
        """exactly 32 chars accepted."""
        from src.modules.memvault.kg_schemas import TripleCreate

        triple = TripleCreate(
            subject="s",
            predicate="p",
            object="o",
            evidence_method="x" * 32,
        )
        assert len(triple.evidence_method) == 32


class TestEnrichCitationsEdges:
    """_enrich_citations_with_signal 異常輸入處理."""

    def test_empty_list(self):
        from src.modules.docvault.qa_service import _enrich_citations_with_signal

        result = _enrich_citations_with_signal(
            [], overall_confidence=0.5, crag_verdict=None
        )
        assert result == []

    def test_citation_without_score_uses_overall(self):
        from src.modules.docvault.qa_service import _enrich_citations_with_signal

        result = _enrich_citations_with_signal(
            [{"document_id": "d1"}],
            overall_confidence=0.85,
            crag_verdict="correct",
        )
        assert len(result) == 1
        assert result[0].confidence == 0.85
        assert result[0].confidence_type == "extracted"

    def test_citation_explicit_confidence_not_overwritten(self):
        from src.modules.docvault.qa_service import _enrich_citations_with_signal

        result = _enrich_citations_with_signal(
            [
                {
                    "document_id": "d1",
                    "confidence": 0.99,
                    "confidence_type": "extracted",
                }
            ],
            overall_confidence=0.1,
            crag_verdict="incorrect",  # 應強制 ambiguous，但顯式給的不覆寫
        )
        assert result[0].confidence == 0.99
        assert result[0].confidence_type == "extracted"

    def test_overall_confidence_zero_with_unknown_verdict(self):
        from src.modules.docvault.qa_service import _enrich_citations_with_signal

        result = _enrich_citations_with_signal(
            [{"document_id": "d1"}], overall_confidence=0.0, crag_verdict=None
        )
        assert result[0].confidence_type == "ambiguous"


class TestVerifyStrategyEdges:
    """_verify_strategy_from_signal 對未知 signal 的處理."""

    def test_unknown_signal_falls_to_extracted(self):
        from src.modules.memvault.crag_evaluator import _verify_strategy_from_signal

        # 未知 signal 落到 'extracted' default (見 helper else branch)
        result = _verify_strategy_from_signal("totally_unknown")
        assert "force_web_verify" in result
        assert "promote_threshold" in result
        # 預期當 extracted default
        assert result["force_web_verify"] is False


# ============================================================================
# 鐵律 6 — Regression
# ============================================================================


class TestRegressionExistingBehavior:
    """確保 evidence_signal 加入不破壞既有 CRAG/Triple 行為."""

    def test_signal_from_score_hard_assertions(self):
        """五個 representative confidence 值 hard assertion — 防 boundary 偷改."""
        from src.modules.memvault.crag_evaluator import signal_from_score

        assert signal_from_score(0.0) == "ambiguous"
        assert signal_from_score(0.25) == "ambiguous"
        assert signal_from_score(0.5) == "inferred"
        assert signal_from_score(0.75) == "inferred"
        assert signal_from_score(1.0) == "extracted"

    def test_kg_models_triple_still_importable(self):
        """Triple ORM 加 evidence_signal 後其他 import 不退化."""
        from src.modules.memvault.kg_models import Triple

        # 確認新欄位存在
        assert hasattr(Triple, "evidence_signal")
        assert hasattr(Triple, "evidence_method")
        # 確認既有欄位仍在（隨機 sample）
        assert hasattr(Triple, "subject")
        assert hasattr(Triple, "predicate")
        assert hasattr(Triple, "object")
        assert hasattr(Triple, "confidence")
        assert hasattr(Triple, "verification_status")  # Phase F+G

    def test_kg_schemas_triple_create_still_works_minimal(self):
        """最少欄位的 TripleCreate 仍可建立（向前相容）."""
        from src.modules.memvault.kg_schemas import TripleCreate

        triple = TripleCreate(subject="A", predicate="rel", object="B")
        assert triple.subject == "A"
        # 預設 evidence_signal='extracted'
        assert triple.evidence_signal == "extracted"
        assert triple.evidence_method is None

    def test_citation_ref_still_works_minimal(self):
        """最少欄位 CitationRef 向前相容."""
        from src.modules.docvault.schemas import CitationRef

        cite = CitationRef(document_id="doc-1")
        assert cite.document_id == "doc-1"
        assert cite.confidence is None
        assert cite.confidence_type is None

    def test_evidence_signal_boundaries_match_constants(self):
        """常數值若改，這個測試會失敗 — 防 silent boundary drift."""
        from src.modules.memvault.crag_evaluator import (
            EVIDENCE_SIGNAL_AMBIGUOUS_THRESHOLD,
            EVIDENCE_SIGNAL_EXTRACTED_THRESHOLD,
        )

        # 文件約定：0.4 / 0.8
        assert math.isclose(EVIDENCE_SIGNAL_AMBIGUOUS_THRESHOLD, 0.4)
        assert math.isclose(EVIDENCE_SIGNAL_EXTRACTED_THRESHOLD, 0.8)

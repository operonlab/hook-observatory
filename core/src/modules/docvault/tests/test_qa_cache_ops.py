"""Adversarial tests for DocVault Phase 2 — QA Cache Ops.

Written based on Op contracts ONLY, not implementation.
Mutation thinking: thresholds, empty inputs, None values, division by zero.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ════════════════════════════════════════════════════
# QAGenerationOp tests
# ════════════════════════════════════════════════════


class TestDecideQACount:
    """Test _decide_qa_count adaptive logic — adversarial boundary mutations."""

    def test_small_document(self):
        from src.modules.docvault.ops.qa_generation import _decide_qa_count

        assert _decide_qa_count(1) == 10
        assert _decide_qa_count(5) == 10
        assert _decide_qa_count(9) == 10

    def test_medium_document(self):
        from src.modules.docvault.ops.qa_generation import _decide_qa_count

        assert _decide_qa_count(10) == 20
        assert _decide_qa_count(20) == 20
        assert _decide_qa_count(29) == 20

    def test_large_document(self):
        from src.modules.docvault.ops.qa_generation import _decide_qa_count

        assert _decide_qa_count(30) == 40
        assert _decide_qa_count(100) == 40

    def test_zero_chunks(self):
        from src.modules.docvault.ops.qa_generation import _decide_qa_count

        assert _decide_qa_count(0) == 10  # < 10 path

    def test_boundary_exactly_10_is_medium_not_small(self):
        """10 is NOT <10 → must return 20, not 10.

        Mutation guard: changing `< 10` to `<= 10` would return 10 here.
        """
        from src.modules.docvault.ops.qa_generation import _decide_qa_count

        assert _decide_qa_count(10) == 20

    def test_boundary_exactly_30_is_large_not_medium(self):
        """30 is NOT <30 → must return 40, not 20.

        Mutation guard: changing `< 30` to `<= 30` would return 20 here.
        """
        from src.modules.docvault.ops.qa_generation import _decide_qa_count

        assert _decide_qa_count(30) == 40

    def test_returns_int_not_float(self):
        """Return type must be int, not float (e.g., not 10.0)."""
        from src.modules.docvault.ops.qa_generation import _decide_qa_count

        result = _decide_qa_count(5)
        assert isinstance(result, int)

    def test_three_distinct_return_values_only(self):
        """Only 10, 20, 40 are valid outputs — no other values."""
        from src.modules.docvault.ops.qa_generation import _decide_qa_count

        for n in range(0, 101):
            assert _decide_qa_count(n) in (10, 20, 40)


class TestQAGenerationOpDisabled:
    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self):
        with patch.dict(os.environ, {"DOCVAULT_QA_GENERATION": "0"}, clear=False):
            # Re-import to pick up env
            import importlib

            import src.modules.docvault.ops.qa_generation as mod

            importlib.reload(mod)

            op = mod.QAGenerationOp()
            ctx = {
                "chunks": [{"content": "test"}],
                "document_id": "doc1",
                "version_id": "ver1",
                "space_id": "default",
                "db": MagicMock(),
            }
            result = await op(ctx)
            assert result["generated_qa_pairs"] == []
            assert result["qa_generation_count"] == 0


# ════════════════════════════════════════════════════
# QAValidationOp tests
# ════════════════════════════════════════════════════


class TestValidateAnswerSpans:
    def test_empty_answer(self):
        from src.modules.docvault.ops.qa_validation import _validate_answer_spans

        assert _validate_answer_spans("", [{"content": "test"}]) is False

    def test_empty_chunks(self):
        from src.modules.docvault.ops.qa_validation import _validate_answer_spans

        assert _validate_answer_spans("some answer", []) is False

    def test_both_empty(self):
        from src.modules.docvault.ops.qa_validation import _validate_answer_spans

        assert _validate_answer_spans("", []) is False

    def test_numbers_present_in_chunks(self):
        from src.modules.docvault.ops.qa_validation import _validate_answer_spans

        answer = "The price is $500 and delivery takes 3 days"
        chunks = [{"content": "Our product costs $500 with a 3-day delivery guarantee"}]
        assert _validate_answer_spans(answer, chunks) is True

    def test_numbers_missing_from_chunks(self):
        from src.modules.docvault.ops.qa_validation import _validate_answer_spans

        answer = "The price is $999 and delivery takes 7 days"
        chunks = [{"content": "Our product costs $500 with a 3-day delivery"}]
        assert _validate_answer_spans(answer, chunks) is False

    def test_no_numbers_but_good_overlap(self):
        from src.modules.docvault.ops.qa_validation import _validate_answer_spans

        answer = "The product is available in red and blue colors"
        chunks = [{"content": "Available colors include red, blue, and green for this product"}]
        assert _validate_answer_spans(answer, chunks) is True

    def test_low_word_overlap(self):
        from src.modules.docvault.ops.qa_validation import _validate_answer_spans

        answer = "quantum entanglement produces fascinating results"
        chunks = [{"content": "the weather is sunny and warm today"}]
        assert _validate_answer_spans(answer, chunks) is False

    def test_string_chunks(self):
        """Chunks can be plain strings, not just dicts."""
        from src.modules.docvault.ops.qa_validation import _validate_answer_spans

        answer = "The cat sat on the mat"
        chunks = ["The cat sat on the mat in the morning"]
        assert _validate_answer_spans(answer, chunks) is True


class TestQAValidationOpDisabled:
    @pytest.mark.asyncio
    async def test_disabled_returns_zeros(self):
        with patch.dict(os.environ, {"DOCVAULT_QA_VALIDATION": "0"}, clear=False):
            import importlib

            import src.modules.docvault.ops.qa_validation as mod

            importlib.reload(mod)

            op = mod.QAValidationOp()
            ctx = {"generated_qa_pairs": [], "chunks": [], "db": None}
            result = await op(ctx)
            assert result["validated_qa_count"] == 0
            assert result["rejected_qa_count"] == 0


# ════════════════════════════════════════════════════
# QACacheLookupOp tests
# ════════════════════════════════════════════════════


class TestQACacheLookupThresholds:
    def test_threshold_constants(self):
        from src.modules.docvault.ops.qa_cache_lookup import (
            FAQ_CACHE_THRESHOLD,
            SYSTEM_CACHE_THRESHOLD,
        )

        assert SYSTEM_CACHE_THRESHOLD == 0.85
        assert FAQ_CACHE_THRESHOLD == 0.90
        assert FAQ_CACHE_THRESHOLD > SYSTEM_CACHE_THRESHOLD


class TestQACacheLookupOpDisabled:
    @pytest.mark.asyncio
    async def test_disabled_returns_miss(self):
        with patch.dict(os.environ, {"DOCVAULT_QA_CACHE": "0"}, clear=False):
            import importlib

            import src.modules.docvault.ops.qa_cache_lookup as mod

            importlib.reload(mod)

            op = mod.QACacheLookupOp()
            ctx = {"query": "test question", "space_id": "default"}
            result = await op(ctx)
            assert result["cache_hit"] is False

    @pytest.mark.asyncio
    async def test_disabled_with_empty_query(self):
        with patch.dict(os.environ, {"DOCVAULT_QA_CACHE": "0"}, clear=False):
            import importlib

            import src.modules.docvault.ops.qa_cache_lookup as mod

            importlib.reload(mod)

            op = mod.QACacheLookupOp()
            ctx = {"query": "", "space_id": "default"}
            result = await op(ctx)
            assert result["cache_hit"] is False


class TestQACacheLookupOpEnabled:
    @pytest.mark.asyncio
    async def test_cache_hit_system(self):
        with patch.dict(os.environ, {"DOCVAULT_QA_CACHE": "1"}, clear=False):
            import importlib

            import src.modules.docvault.ops.qa_cache_lookup as mod

            importlib.reload(mod)

            mock_result = [
                {
                    "score": 0.90,
                    "metadata": {
                        "full_answer": "Cached answer text",
                        "answer_preview": "Cached",
                    },
                }
            ]
            with patch("src.shared.qdrant_search.hybrid_search", new_callable=AsyncMock) as mock_search:
                mock_search.return_value = mock_result
                op = mod.QACacheLookupOp()
                ctx = {"query": "test question", "space_id": "default"}
                result = await op(ctx)

                assert result["cache_hit"] is True
                assert result["cached_answer"] == "Cached answer text"
                assert result["cache_source"] == "cached"
                assert result["cache_confidence"] == 0.90

    @pytest.mark.asyncio
    async def test_cache_miss_below_threshold(self):
        with patch.dict(os.environ, {"DOCVAULT_QA_CACHE": "1"}, clear=False):
            import importlib

            import src.modules.docvault.ops.qa_cache_lookup as mod

            importlib.reload(mod)

            mock_result = [{"score": 0.80, "metadata": {"full_answer": "Low score"}}]
            with patch("src.shared.qdrant_search.hybrid_search", new_callable=AsyncMock) as mock_search:
                mock_search.return_value = mock_result
                op = mod.QACacheLookupOp()
                ctx = {"query": "test", "space_id": "default"}
                result = await op(ctx)
                assert result["cache_hit"] is False

    @pytest.mark.asyncio
    async def test_empty_query_returns_miss(self):
        with patch.dict(os.environ, {"DOCVAULT_QA_CACHE": "1"}, clear=False):
            import importlib

            import src.modules.docvault.ops.qa_cache_lookup as mod

            importlib.reload(mod)

            op = mod.QACacheLookupOp()
            ctx = {"query": "", "space_id": "default"}
            result = await op(ctx)
            assert result["cache_hit"] is False


# ════════════════════════════════════════════════════
# QAFeedbackLoopOp tests
# ════════════════════════════════════════════════════


class TestQAFeedbackLoopThreshold:
    def test_threshold_constant(self):
        from src.modules.docvault.ops.qa_feedback_loop import PROMOTE_CONFIDENCE_THRESHOLD

        assert PROMOTE_CONFIDENCE_THRESHOLD == 0.7


class TestQAFeedbackLoopOpDisabled:
    @pytest.mark.asyncio
    async def test_disabled_no_promote(self):
        with patch.dict(os.environ, {"DOCVAULT_QA_FAQ_PROMOTE": "0"}, clear=False):
            import importlib

            import src.modules.docvault.ops.qa_feedback_loop as mod

            importlib.reload(mod)

            op = mod.QAFeedbackLoopOp()
            ctx = {
                "qa_log_id": "log1",
                "feedback": "positive",
                "confidence": 0.9,
                "query_text": "test",
                "answer_text": "answer",
            }
            result = await op(ctx)
            assert result["faq_promoted"] is False


class TestQAFeedbackLoopOpEnabled:
    @pytest.mark.asyncio
    async def test_negative_feedback_no_promote(self):
        with patch.dict(os.environ, {"DOCVAULT_QA_FAQ_PROMOTE": "1"}, clear=False):
            import importlib

            import src.modules.docvault.ops.qa_feedback_loop as mod

            importlib.reload(mod)

            op = mod.QAFeedbackLoopOp()
            ctx = {
                "qa_log_id": "log1",
                "feedback": "negative",
                "confidence": 0.9,
                "query_text": "test",
                "answer_text": "answer",
            }
            result = await op(ctx)
            assert result["faq_promoted"] is False

    @pytest.mark.asyncio
    async def test_low_confidence_no_promote(self):
        with patch.dict(os.environ, {"DOCVAULT_QA_FAQ_PROMOTE": "1"}, clear=False):
            import importlib

            import src.modules.docvault.ops.qa_feedback_loop as mod

            importlib.reload(mod)

            op = mod.QAFeedbackLoopOp()
            ctx = {
                "qa_log_id": "log1",
                "feedback": "positive",
                "confidence": 0.5,
                "query_text": "test",
                "answer_text": "answer",
            }
            result = await op(ctx)
            assert result["faq_promoted"] is False

    @pytest.mark.asyncio
    async def test_boundary_confidence_promotes(self):
        """Confidence exactly at threshold should promote."""
        with patch.dict(os.environ, {"DOCVAULT_QA_FAQ_PROMOTE": "1"}, clear=False):
            import importlib

            import src.modules.docvault.ops.qa_feedback_loop as mod

            importlib.reload(mod)

            with patch(
                "src.shared.qdrant_search.index_documents_batch",
                new_callable=AsyncMock,
            ) as mock_index:
                mock_index.return_value = 1
                op = mod.QAFeedbackLoopOp()
                ctx = {
                    "qa_log_id": "log1",
                    "feedback": "positive",
                    "confidence": 0.7,
                    "query_text": "test q",
                    "answer_text": "test a",
                }
                result = await op(ctx)
                assert result["faq_promoted"] is True

    @pytest.mark.asyncio
    async def test_empty_query_no_promote(self):
        with patch.dict(os.environ, {"DOCVAULT_QA_FAQ_PROMOTE": "1"}, clear=False):
            import importlib

            import src.modules.docvault.ops.qa_feedback_loop as mod

            importlib.reload(mod)

            op = mod.QAFeedbackLoopOp()
            ctx = {
                "qa_log_id": "log1",
                "feedback": "positive",
                "confidence": 0.9,
                "query_text": "",
                "answer_text": "answer",
            }
            result = await op(ctx)
            assert result["faq_promoted"] is False


# ════════════════════════════════════════════════════
# Schema tests
# ════════════════════════════════════════════════════


class TestSchemaBackwardCompatibility:
    def test_qa_request_without_session_id(self):
        from src.modules.docvault.schemas import QARequest

        req = QARequest(question="test?")
        assert req.session_id is None
        assert req.question == "test?"

    def test_qa_request_with_session_id(self):
        from src.modules.docvault.schemas import QARequest

        req = QARequest(question="test?", session_id="sess123")
        assert req.session_id == "sess123"

    def test_qa_log_create_cache_pipeline(self):
        from src.modules.docvault.schemas import QALogCreate

        log = QALogCreate(
            query_text="q",
            query_hash="abc123",
            answer_text="a",
            pipeline_used="cache",
        )
        assert log.pipeline_used == "cache"

    def test_qa_log_create_old_pipelines_still_valid(self):
        from src.modules.docvault.schemas import QALogCreate

        for pipeline in ("A", "B", "C"):
            log = QALogCreate(
                query_text="q",
                query_hash="abc123",
                answer_text="a",
                pipeline_used=pipeline,
            )
            assert log.pipeline_used == pipeline

    def test_qa_log_create_invalid_pipeline_rejected(self):
        from pydantic import ValidationError

        from src.modules.docvault.schemas import QALogCreate

        with pytest.raises(ValidationError):
            QALogCreate(
                query_text="q",
                query_hash="abc123",
                answer_text="a",
                pipeline_used="X",
            )

    def test_qa_response_new_fields(self):
        from src.modules.docvault.schemas import QAResponse

        resp = QAResponse(
            question="q",
            answer="a",
            session_id="sess1",
            turn_number=3,
        )
        assert resp.session_id == "sess1"
        assert resp.turn_number == 3

    def test_qa_response_without_new_fields(self):
        from src.modules.docvault.schemas import QAResponse

        resp = QAResponse(question="q", answer="a")
        assert resp.session_id is None
        assert resp.turn_number is None

    def test_pre_generated_qa_response(self):
        from datetime import datetime

        from src.modules.docvault.schemas import PreGeneratedQAResponse

        resp = PreGeneratedQAResponse(
            id="id1",
            space_id="default",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            document_id="doc1",
            version_id="ver1",
            question="What is X?",
            answer="X is Y",
            question_type="factual",
            confidence=0.8,
            status="validated",
            reuse_count=5,
        )
        assert resp.question == "What is X?"
        assert resp.reuse_count == 5

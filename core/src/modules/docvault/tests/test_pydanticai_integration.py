"""PydanticAI Integration Tests — llm_models, llm_config, cited_answer, query_expand, chunk_entity.

Test-adversary written: only signatures and docstrings were read, not function bodies.
Each test is designed to catch a specific mutation.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from ..llm_models import (
    CommunitySummaryResult,
    ExpandedQueries,
    MissedContent,
    RewriteResult,
    SynthResult,
    VerifyResult,
)

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _make_agent_result(output):
    """Create a mock AgentRunResult with the given output."""
    result = MagicMock()
    result.output = output
    return result


def _fake_chunks(n: int = 3) -> list[dict]:
    return [
        {
            "id": f"chunk-{i}",
            "content": f"Evidence sentence {i}.",
            "section_path": f"Section {i}",
            "page_range": str(i),
            "document_id": "doc-001",
        }
        for i in range(1, n + 1)
    ]


# ─────────────────────────────────────────────
# A. Pydantic Model Validation (llm_models.py)
# ─────────────────────────────────────────────


class TestSynthResult:
    def test_confidence_upper_clamp_raises(self):
        """confidence > 1.0 must raise ValidationError.

        Mutation: removing `le=1.0` from Field would survive without this test.
        """
        with pytest.raises(ValidationError):
            SynthResult(confidence=1.5)

    def test_confidence_lower_clamp_raises(self):
        """confidence < 0.0 must raise ValidationError.

        Mutation: removing `ge=0.0` from Field would survive without this test.
        """
        with pytest.raises(ValidationError):
            SynthResult(confidence=-0.1)

    def test_confidence_boundary_valid(self):
        """confidence=0.0 and confidence=1.0 must both be valid.

        Mutation: changing ge/le to gt/lt would break boundary values.
        """
        s_low = SynthResult(confidence=0.0)
        s_high = SynthResult(confidence=1.0)
        assert s_low.confidence == 0.0
        assert s_high.confidence == 1.0

    def test_default_answer_is_none(self):
        """answer must default to None, not empty string.

        Mutation: changing `answer: str | None = None` to `answer: str = ""`
        would survive without this test.
        """
        s = SynthResult()
        assert s.answer is None

    def test_default_confidence_is_half(self):
        """confidence must default to 0.5.

        Mutation: changing default=0.5 to default=0.0 would survive without this test.
        """
        s = SynthResult()
        assert s.confidence == 0.5

    def test_default_terminology_match_is_true(self):
        """terminology_match must default to True.

        Mutation: flipping default to False would cause all answers to be capped at 0.2
        confidence by default.
        """
        s = SynthResult()
        assert s.terminology_match is True

    def test_citations_used_defaults_empty(self):
        """citations_used must default to an empty list (not shared mutable default).

        Mutation: using `citations_used: list[int] = []` (non-factory) would be a
        mutable-default bug; this test verifies independence.
        """
        s1 = SynthResult()
        s2 = SynthResult()
        s1.citations_used.append(99)
        assert 99 not in s2.citations_used


class TestVerifyResult:
    def test_defaults_empty_lists(self):
        """missed and analogies must both default to empty lists.

        Mutation: removing Field(default_factory=list) for either field and defaulting
        to None would change external callers that iterate these.
        """
        v = VerifyResult()
        assert v.missed == []
        assert v.analogies == []

    def test_missed_independence(self):
        """Two VerifyResult instances must have independent missed lists.

        Mutation: shared mutable default `missed: list = []` would cause cross-instance
        contamination.
        """
        v1 = VerifyResult()
        v2 = VerifyResult()
        v1.missed.append(MissedContent(text="x"))
        assert len(v2.missed) == 0


class TestCommunitySummaryResult:
    def test_summary_is_required(self):
        """summary field must be required — omitting it should raise ValidationError.

        Mutation: giving summary a default value would break the contract that a summary
        always has real content.
        """
        with pytest.raises(ValidationError):
            CommunitySummaryResult()

    def test_summary_accepted(self):
        """Valid summary must be stored verbatim."""
        r = CommunitySummaryResult(summary="Key finding about data quality.")
        assert r.summary == "Key finding about data quality."

    def test_key_findings_defaults_empty(self):
        """key_findings must default to empty list, not None.

        Mutation: changing to `key_findings: list[str] | None = None` would break callers
        that iterate without None-checks.
        """
        r = CommunitySummaryResult(summary="Some summary.")
        assert r.key_findings == []


class TestRewriteResult:
    def test_query_is_required(self):
        """query field must be required — omitting it should raise ValidationError.

        Mutation: defaulting query to "" would allow empty rewrites to pass through silently.
        """
        with pytest.raises(ValidationError):
            RewriteResult()

    def test_query_stored_verbatim(self):
        """query value must be stored as-is."""
        r = RewriteResult(query="revised question about billing cycle")
        assert r.query == "revised question about billing cycle"


# ─────────────────────────────────────────────
# B. Model Resolution (llm_config.py)
# ─────────────────────────────────────────────


class TestResolveModel:
    @pytest.mark.asyncio
    async def test_returns_first_matching_candidate(self):
        """resolve_model must return the first candidate that appears in /v1/models.

        Mutation: returning the last matching candidate instead of the first would survive
        without this test.
        """
        from ..llm_config import resolve_model

        available_models = ["kimi-k2.5", "deepseek-v3"]  # NOT first candidate

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"id": m} for m in available_models]}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with (
            patch("src.modules.docvault.llm_config._cached_model", None),
            patch("src.modules.docvault.llm_config._cached_model_ts", 0.0),
            patch("src.modules.docvault.llm_config.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await resolve_model(
                candidates=["gemini-3.1-flash-lite", "kimi-k2.5", "deepseek-v3"]
            )

        # kimi-k2.5 is first in candidates that also appears in available_models
        assert result == "kimi-k2.5"

    @pytest.mark.asyncio
    async def test_returns_default_when_litellm_unreachable(self):
        """resolve_model must return candidates[0] when LiteLLM raises.

        Mutation: re-raising the exception instead of falling back would crash callers.
        """
        import httpx as httpx_mod

        from ..llm_config import resolve_model

        with (
            patch("src.modules.docvault.llm_config._cached_model", None),
            patch("src.modules.docvault.llm_config._cached_model_ts", 0.0),
            patch(
                "src.modules.docvault.llm_config.httpx.AsyncClient",
                side_effect=httpx_mod.ConnectError("refused"),
            ),
        ):
            candidates = ["model-alpha", "model-beta"]
            result = await resolve_model(candidates=candidates)

        assert result == "model-alpha"

    @pytest.mark.asyncio
    async def test_caches_result_on_second_call(self):
        """resolve_model must not call httpx again within TTL window.

        Mutation: removing cache check (`if _cached_model …`) would double the network
        calls and was a real performance regression in a prior review.
        """
        from ..llm_config import resolve_model

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"id": "gemini-3.1-flash-lite"}]}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        now = time.monotonic()

        with (
            patch("src.modules.docvault.llm_config._cached_model", None),
            patch("src.modules.docvault.llm_config._cached_model_ts", 0.0),
            patch(
                "src.modules.docvault.llm_config.httpx.AsyncClient", return_value=mock_client
            ) as MockCls,
        ):
            await resolve_model()
            MockCls.reset_mock()
            # Second call immediately — should hit cache
            await resolve_model()
            MockCls.assert_not_called()

    def test_make_model_returns_openai_chat_model(self):
        """make_model must return an OpenAIChatModel instance.

        Mutation: returning a different model type would break all downstream agent
        model= arguments.
        """
        from pydantic_ai.models.openai import OpenAIChatModel

        from ..llm_config import make_model

        m = make_model("test-model")
        assert isinstance(m, OpenAIChatModel)


# ─────────────────────────────────────────────
# C. CitedAnswerOp Behavior
# ─────────────────────────────────────────────


class TestCitedAnswerOp:
    @pytest.mark.asyncio
    async def test_terminology_mismatch_caps_confidence(self):
        """When terminology_match=False, confidence must be ≤ 0.5.

        Mutation: removing `min(confidence, 0.5)` would allow full-confidence
        answers through even when terminology doesn't match.
        """
        from ..ops.cited_answer import CitedAnswerOp

        synth_output = SynthResult(
            answer="Some answer [1]",
            citations_used=[1],
            terminology_match=False,
            confidence=0.9,
        )
        verify_output = VerifyResult()

        mock_synth_result = _make_agent_result(synth_output)
        mock_verify_result = _make_agent_result(verify_output)

        with (
            patch("src.modules.docvault.ops.cited_answer._synth_agent") as mock_synth,
            patch("src.modules.docvault.ops.cited_answer._verify_agent") as mock_verify,
            patch(
                "src.modules.docvault.ops.cited_answer.get_model", new_callable=AsyncMock
            ) as mock_get_model,
        ):
            mock_synth.run = AsyncMock(return_value=mock_synth_result)
            mock_verify.run = AsyncMock(return_value=mock_verify_result)
            mock_get_model.return_value = MagicMock()

            op = CitedAnswerOp()
            ctx = {
                "question": "What is X?",
                "evidence_chunks": _fake_chunks(2),
            }
            result = await op(ctx)

        assert result["confidence"] <= 0.5

    @pytest.mark.asyncio
    async def test_empty_answer_returns_refusal_with_zero_confidence(self):
        """When synth answer is empty/None, must return confidence=0.0.

        Mutation: returning confidence=0.5 on refusal would misleadingly score a
        non-answer as moderate quality.
        """
        from ..ops.cited_answer import CitedAnswerOp

        synth_output = SynthResult(
            answer=None,  # empty
            citations_used=[],
            terminology_match=True,
            confidence=0.8,
            reason="Not found in document.",
        )
        verify_output = VerifyResult()

        mock_synth_result = _make_agent_result(synth_output)
        mock_verify_result = _make_agent_result(verify_output)

        with (
            patch("src.modules.docvault.ops.cited_answer._synth_agent") as mock_synth,
            patch("src.modules.docvault.ops.cited_answer._verify_agent") as mock_verify,
            patch(
                "src.modules.docvault.ops.cited_answer.get_model", new_callable=AsyncMock
            ) as mock_get_model,
        ):
            mock_synth.run = AsyncMock(return_value=mock_synth_result)
            mock_verify.run = AsyncMock(return_value=mock_verify_result)
            mock_get_model.return_value = MagicMock()

            op = CitedAnswerOp()
            ctx = {
                "question": "What is Y?",
                "evidence_chunks": _fake_chunks(1),
            }
            result = await op(ctx)

        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_empty_answer_returns_non_empty_message(self):
        """When answer is empty, the refusal message must be a non-empty string.

        Mutation: returning answer="" on refusal would break callers that check
        truthiness of the answer field.
        """
        from ..ops.cited_answer import CitedAnswerOp

        synth_output = SynthResult(
            answer="   ",  # whitespace only = empty
            reason="No relevant content.",
        )
        verify_output = VerifyResult()

        with (
            patch("src.modules.docvault.ops.cited_answer._synth_agent") as mock_synth,
            patch("src.modules.docvault.ops.cited_answer._verify_agent") as mock_verify,
            patch(
                "src.modules.docvault.ops.cited_answer.get_model", new_callable=AsyncMock
            ) as mock_get_model,
        ):
            mock_synth.run = AsyncMock(return_value=_make_agent_result(synth_output))
            mock_verify.run = AsyncMock(return_value=_make_agent_result(verify_output))
            mock_get_model.return_value = MagicMock()

            op = CitedAnswerOp()
            ctx = {
                "question": "What?",
                "evidence_chunks": _fake_chunks(1),
            }
            result = await op(ctx)

        assert isinstance(result["answer"], str)
        assert len(result["answer"].strip()) > 0

    @pytest.mark.asyncio
    async def test_missed_content_not_in_answer_is_appended(self):
        """When verify finds missed content absent from answer, it must be appended.

        Mutation: removing the novel_missed supplement block would silently drop
        verification-found gaps.
        """
        from ..ops.cited_answer import CitedAnswerOp

        original_answer = "Only first fact [1]."
        missed_text = "completely_distinct_missed_fact_xyz"

        synth_output = SynthResult(
            answer=original_answer,
            citations_used=[1],
            terminology_match=True,
            confidence=0.8,
        )
        verify_output = VerifyResult(
            missed=[MissedContent(text=missed_text, chunk=2)],
        )

        with (
            patch("src.modules.docvault.ops.cited_answer._synth_agent") as mock_synth,
            patch("src.modules.docvault.ops.cited_answer._verify_agent") as mock_verify,
            patch(
                "src.modules.docvault.ops.cited_answer.get_model", new_callable=AsyncMock
            ) as mock_get_model,
        ):
            mock_synth.run = AsyncMock(return_value=_make_agent_result(synth_output))
            mock_verify.run = AsyncMock(return_value=_make_agent_result(verify_output))
            mock_get_model.return_value = MagicMock()

            op = CitedAnswerOp()
            ctx = {
                "question": "Tell me everything.",
                "evidence_chunks": _fake_chunks(3),
            }
            result = await op(ctx)

        # The missed fact should have been appended to the answer
        assert missed_text in result["answer"]

    @pytest.mark.asyncio
    async def test_output_keys_present_in_ctx(self):
        """CitedAnswerOp.__call__ must produce answer, citations, confidence in ctx.

        Mutation: renaming any output key would break downstream ops that depend on
        the operator protocol.
        """
        from ..ops.cited_answer import CitedAnswerOp

        synth_output = SynthResult(
            answer="Valid answer [1].",
            citations_used=[1],
            terminology_match=True,
            confidence=0.75,
        )
        verify_output = VerifyResult()

        with (
            patch("src.modules.docvault.ops.cited_answer._synth_agent") as mock_synth,
            patch("src.modules.docvault.ops.cited_answer._verify_agent") as mock_verify,
            patch(
                "src.modules.docvault.ops.cited_answer.get_model", new_callable=AsyncMock
            ) as mock_get_model,
        ):
            mock_synth.run = AsyncMock(return_value=_make_agent_result(synth_output))
            mock_verify.run = AsyncMock(return_value=_make_agent_result(verify_output))
            mock_get_model.return_value = MagicMock()

            op = CitedAnswerOp()
            ctx = {
                "question": "What is Z?",
                "evidence_chunks": _fake_chunks(2),
            }
            result = await op(ctx)

        assert "answer" in result
        assert "citations" in result
        assert "confidence" in result
        assert isinstance(result["citations"], list)
        assert isinstance(result["confidence"], float)


# ─────────────────────────────────────────────
# D. QueryExpandOp Behavior
# ─────────────────────────────────────────────


class TestQueryExpandOp:
    @pytest.mark.asyncio
    async def test_original_question_always_first(self):
        """Original question must always be the first element in expanded_queries.

        Mutation: building queries as [*agent_results, original] would put the original
        last, losing its priority in retrieval ordering.
        """
        from ..ops.query_expand import QueryExpandOp

        expand_output = ExpandedQueries(queries=["sub-q A", "sub-q B", "sub-q C"])

        with (
            patch("src.modules.docvault.ops.query_expand._expand_agent") as mock_agent,
            patch(
                "src.modules.docvault.ops.query_expand.get_model", new_callable=AsyncMock
            ) as mock_get_model,
        ):
            mock_agent.run = AsyncMock(return_value=_make_agent_result(expand_output))
            mock_get_model.return_value = MagicMock()

            op = QueryExpandOp()
            original = "What are the main findings?"
            ctx = {"query": original}
            result = await op(ctx)

        queries = result["expanded_queries"]
        assert queries[0] == original

    @pytest.mark.asyncio
    async def test_max_four_queries_returned(self):
        """Even if agent returns more than 3 sub-queries, total must be capped at 4.

        Mutation: removing `[:4]` cap would allow unbounded retrieval fan-out, causing
        downstream latency issues.
        """
        from ..ops.query_expand import QueryExpandOp

        # 10 sub-queries from the agent — more than the cap
        expand_output = ExpandedQueries(queries=[f"q{i}" for i in range(10)])

        with (
            patch("src.modules.docvault.ops.query_expand._expand_agent") as mock_agent,
            patch(
                "src.modules.docvault.ops.query_expand.get_model", new_callable=AsyncMock
            ) as mock_get_model,
        ):
            mock_agent.run = AsyncMock(return_value=_make_agent_result(expand_output))
            mock_get_model.return_value = MagicMock()

            op = QueryExpandOp()
            ctx = {"query": "original question"}
            result = await op(ctx)

        assert len(result["expanded_queries"]) <= 4

    @pytest.mark.asyncio
    async def test_agent_failure_returns_original_only(self):
        """When agent.run raises, expanded_queries must contain only the original question.

        Mutation: re-raising the exception instead of swallowing it would crash the
        entire RAG pipeline on any LLM timeout.
        """
        from ..ops.query_expand import QueryExpandOp

        with (
            patch("src.modules.docvault.ops.query_expand._expand_agent") as mock_agent,
            patch(
                "src.modules.docvault.ops.query_expand.get_model", new_callable=AsyncMock
            ) as mock_get_model,
        ):
            mock_agent.run = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
            mock_get_model.return_value = MagicMock()

            op = QueryExpandOp()
            original = "Fallback question"
            ctx = {"query": original}
            result = await op(ctx)

        assert result["expanded_queries"] == [original]

    @pytest.mark.asyncio
    async def test_duplicate_of_original_not_added(self):
        """Agent returning the original question as one of its queries must not duplicate it.

        Mutation: removing `if q.strip() != question` check would add the original twice,
        causing redundant retrieval and misleading result counts.
        """
        from ..ops.query_expand import QueryExpandOp

        original = "How does caching work?"
        # Agent echoes the original plus one unique sub-query
        expand_output = ExpandedQueries(queries=[original, "cache invalidation strategies"])

        with (
            patch("src.modules.docvault.ops.query_expand._expand_agent") as mock_agent,
            patch(
                "src.modules.docvault.ops.query_expand.get_model", new_callable=AsyncMock
            ) as mock_get_model,
        ):
            mock_agent.run = AsyncMock(return_value=_make_agent_result(expand_output))
            mock_get_model.return_value = MagicMock()

            op = QueryExpandOp()
            ctx = {"query": original}
            result = await op(ctx)

        queries = result["expanded_queries"]
        assert queries.count(original) == 1


# ─────────────────────────────────────────────
# E. chunk_entity.py Retry Behavior
# ─────────────────────────────────────────────


class TestChunkEntityRetry:
    @pytest.mark.asyncio
    async def test_retry_on_transient_failure(self):
        """extract_triples failing once then succeeding must produce non-empty triples.

        Mutation: removing `@retry(stop=stop_after_attempt(2))` would cause a single LLM
        hiccup to produce empty triples, silently degrading KG quality.
        """
        from ..ops.chunk_entity import _extract_chunk_triples

        call_count = 0

        async def flaky_extract(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient LLM error")
            return [{"subject": "A", "predicate": "relates_to", "object": "B"}]

        semaphore = asyncio.Semaphore(5)
        chunk = {"content": "A relates to B in the context of this document."}

        with patch(
            "src.modules.docvault.ops.chunk_entity.extract_triples", side_effect=flaky_extract
        ):
            result_chunk, triples = await _extract_chunk_triples(
                chunk,
                llm_base_url="http://localhost:4000/v1",
                llm_api_key="sk-test",
                model="deepseek-v3",
                max_triples=5,
                semaphore=semaphore,
            )

        # After retry, triples must be populated
        assert len(triples) > 0
        assert call_count == 2  # first failed, second succeeded

    @pytest.mark.asyncio
    async def test_always_fail_returns_empty_no_crash(self):
        """extract_triples always failing must yield empty triples list, not raise.

        Mutation: removing the try/except around _call_with_retry would propagate the
        exception and crash the entire batch ingestion job.
        """
        from ..ops.chunk_entity import _extract_chunk_triples

        async def always_fail(*args, **kwargs):
            raise RuntimeError("LLM perpetually down")

        semaphore = asyncio.Semaphore(5)
        chunk = {"content": "Some content that cannot be extracted."}

        with patch(
            "src.modules.docvault.ops.chunk_entity.extract_triples", side_effect=always_fail
        ):
            result_chunk, triples = await _extract_chunk_triples(
                chunk,
                llm_base_url="http://localhost:4000/v1",
                llm_api_key="sk-test",
                model="deepseek-v3",
                max_triples=5,
                semaphore=semaphore,
            )

        # No crash, empty triples
        assert triples == []
        assert result_chunk is chunk  # same chunk reference returned

    @pytest.mark.asyncio
    async def test_chunk_entity_op_skips_when_no_db(self):
        """ChunkEntityOp must skip KG extraction when 'db' is absent from ctx.

        Mutation: removing the `if db is None: return` guard would cause an AttributeError
        when callers omit db (e.g., in testing or lightweight ingestion).
        """
        from ..ops.chunk_entity import ChunkEntityOp

        op = ChunkEntityOp()
        ctx = {
            "chunks": _fake_chunks(2),
            "document_id": "doc-001",
            "space_id": "space-001",
            # no "db" key
        }
        result = await op(ctx)

        # Must still produce output keys with zeroed counts
        assert result["entity_count"] == 0
        assert result["triple_count"] == 0
        assert result["doc_entities"] == []
        assert result["doc_triples"] == []

    @pytest.mark.asyncio
    async def test_chunk_entity_op_skips_when_no_chunks(self):
        """ChunkEntityOp must return zeroed output when chunks list is empty.

        Mutation: not short-circuiting on empty chunks would trigger semaphore + gather
        with an empty task list — benign now but fragile as the code evolves.
        """
        from ..ops.chunk_entity import ChunkEntityOp

        op = ChunkEntityOp()
        ctx = {
            "chunks": [],
            "document_id": "doc-001",
            "space_id": "space-001",
            "db": MagicMock(),  # db present but chunks empty
        }
        result = await op(ctx)

        assert result["entity_count"] == 0
        assert result["triple_count"] == 0

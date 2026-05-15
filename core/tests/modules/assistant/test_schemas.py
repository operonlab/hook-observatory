"""Pydantic schema validation tests for the cross-vault QA contract.

六鐵律 disclosure: main-thread author (not 寫測分離). Independent
test-adversary T1d wrote test_normalize_intent.py and ran out of
budget before reaching schemas / classify / dispatch — these three
files were completed by the implementor as regression cover. A future
adversarial pass should re-attack the same surfaces.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.modules.assistant.schemas import (
    AssistantQARequest,
    AssistantQAResponse,
    CrossVaultCitation,
)


# ── AssistantQARequest defaults ────────────────────────────────────────


def test_request_defaults_when_only_question_given():
    r = AssistantQARequest(question="x")
    assert r.routing == "auto"
    assert r.docvault_mode == "factual"
    assert r.memvault_top_k == 5
    assert r.docvault_top_k == 20
    assert r.docvault_space is None
    assert r.docvault_tags is None
    assert r.session_id is None


def test_request_question_empty_string_rejected():
    with pytest.raises(ValidationError):
        AssistantQARequest(question="")


def test_request_question_4001_chars_rejected():
    with pytest.raises(ValidationError):
        AssistantQARequest(question="x" * 4001)


# ── routing pattern enforcement (killer: typo/extra value) ─────────────


@pytest.mark.parametrize("bad", ["bogus", "MEMORY", "Memory", "auto ", " auto", "doc;", ""])
def test_routing_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        AssistantQARequest(question="x", routing=bad)


@pytest.mark.parametrize("good", ["auto", "memory", "doc", "mixed"])
def test_routing_accepts_canonical(good):
    r = AssistantQARequest(question="x", routing=good)
    assert r.routing == good


# ── docvault_mode pattern ──────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["bogus", "Factual", "factual ", "Factual"])
def test_docvault_mode_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        AssistantQARequest(question="x", docvault_mode=bad)


@pytest.mark.parametrize("good", ["factual", "mixed"])
def test_docvault_mode_accepts_canonical(good):
    r = AssistantQARequest(question="x", docvault_mode=good)
    assert r.docvault_mode == good


# ── top_k bounds ───────────────────────────────────────────────────────


def test_memvault_top_k_too_low_rejected():
    with pytest.raises(ValidationError):
        AssistantQARequest(question="x", memvault_top_k=0)


def test_memvault_top_k_too_high_rejected():
    with pytest.raises(ValidationError):
        AssistantQARequest(question="x", memvault_top_k=21)


def test_docvault_top_k_too_high_rejected():
    with pytest.raises(ValidationError):
        AssistantQARequest(question="x", docvault_top_k=51)


# ── docvault_tags type discipline (killer: ints vs strs) ───────────────


def test_docvault_tags_int_list_rejected():
    """Killer: if the schema accidentally accepts ANY list, ints slip in."""
    with pytest.raises(ValidationError):
        AssistantQARequest(question="x", docvault_tags=[1, 2, 3])


def test_docvault_tags_string_not_list_rejected():
    with pytest.raises(ValidationError):
        AssistantQARequest(question="x", docvault_tags="posts")


def test_docvault_tags_empty_list_allowed():
    r = AssistantQARequest(question="x", docvault_tags=[])
    assert r.docvault_tags == []


def test_docvault_tags_string_list_accepted():
    r = AssistantQARequest(question="x", docvault_tags=["a", "b"])
    assert r.docvault_tags == ["a", "b"]


# ── CrossVaultCitation source discipline ───────────────────────────────


@pytest.mark.parametrize("bad", ["mem", "doc", "MEMVAULT", "elsewhere", "memvault "])
def test_citation_source_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        CrossVaultCitation(source=bad)


@pytest.mark.parametrize("good", ["memvault", "docvault"])
def test_citation_source_accepts_canonical(good):
    c = CrossVaultCitation(source=good)
    assert c.source == good


def test_citation_all_optional_fields_default_none():
    c = CrossVaultCitation(source="memvault")
    assert c.score is None
    assert c.block_id is None
    assert c.block_content is None
    assert c.block_type is None
    assert c.document_id is None
    assert c.chunk_id is None
    assert c.section is None
    assert c.quote is None


# ── AssistantQAResponse routing_decision pattern ───────────────────────


@pytest.mark.parametrize("bad", ["auto", "AUTO", "MEMORY", "unknown"])
def test_response_routing_decision_rejects_auto_and_invalid(bad):
    """auto is a request-only value — the response must commit to a concrete decision."""
    with pytest.raises(ValidationError):
        AssistantQAResponse(
            question="x", answer="y", routing_decision=bad
        )


@pytest.mark.parametrize("good", ["memory", "doc", "mixed"])
def test_response_routing_decision_accepts_resolved(good):
    r = AssistantQAResponse(question="x", answer="y", routing_decision=good)
    assert r.routing_decision == good
    # Defaults
    assert r.routing_model == ""
    assert r.routing_fallback is False
    assert r.memvault_hits == 0
    assert r.docvault_hits == 0
    assert r.citations == []
    assert r.docvault_qa_log_id is None


def test_response_citations_are_validated_recursively():
    """Killer: response.citations entries must themselves be valid CrossVaultCitation."""
    with pytest.raises(ValidationError):
        AssistantQAResponse(
            question="x",
            answer="y",
            routing_decision="memory",
            citations=[{"source": "bogus"}],
        )

"""Adversary tests for verify_fold_extractiveness.

Mutation thinking targets:
- threshold edge: cosine == 0.85, mutation '> threshold' vs '>= threshold'
- accepted vs rejected: must be exhaustive partition (no leak / no duplicate)
- empty children: design choice — reject all, not crash
- short-circuit: author skips substring path -> bypassable via embedding mock
- author treats use_embedding=False as 'always accept' rather than 'no embedding fallback'
"""
# ruff: noqa: RUF002

import asyncio

import pytest
from src.modules.memvault.fold_verifier import (
    VerifierResult,
    split_sentences,
    verify_fold_extractiveness,
)


def _run(coro):
    return asyncio.run(coro)


def test_all_substring_grounded_all_accepted():
    """Every sentence is a substring of some child -> rejected must be []."""
    children = ["Alfred is a butler.", "JARVIS is an AI."]
    fold = "Alfred is a butler. JARVIS is an AI."
    result = _run(verify_fold_extractiveness(fold, children, use_embedding=False))
    assert isinstance(result, VerifierResult)
    assert result.rejected == []
    assert len(result.accepted) == 2


def test_no_grounding_all_rejected_when_embedding_disabled():
    """No substring overlap + use_embedding=False -> all rejected."""
    children = ["completely unrelated content"]
    fold = "Alfred is a butler. JARVIS is an AI."
    result = _run(verify_fold_extractiveness(fold, children, use_embedding=False))
    assert result.accepted == [], f"unexpected accepts: {result.accepted}"
    # 2 sentences in fold, both rejected
    assert len(result.rejected) == 2


def test_partition_invariant_accepted_plus_rejected_equals_sentences():
    """INVARIANT: |accepted| + |rejected| == |split_sentences(fold)|.

    No sentence may be lost or duplicated. This is the cornerstone
    invariant. Mutation: author 'continue' on a code path without recording
    -> sentence vanishes from both lists.
    """
    children = ["Alfred is a butler.", "Random other thing."]
    fold = "Alfred is a butler. Moon cheese fact. Random other thing."
    result = _run(verify_fold_extractiveness(fold, children, use_embedding=False))
    sentences = split_sentences(fold)
    assert len(result.accepted) + len(result.rejected) == len(sentences), (
        f"partition invariant broken: accepted={result.accepted!r} "
        f"rejected={result.rejected!r} sentences={sentences!r}"
    )
    # And no sentence appears in BOTH (no double-counting).
    assert set(result.accepted).isdisjoint(set(result.rejected)), (
        "sentence appeared in both accepted and rejected"
    )


def test_partition_no_phantom_sentences():
    """accepted ∪ rejected ⊆ split_sentences(fold).

    Mutation: author appends modified/normalized text -> introduces sentences
    not present in the original split.
    """
    children = ["Alfred is a butler."]
    fold = "Alfred is a butler. Moon cheese fact."
    result = _run(verify_fold_extractiveness(fold, children, use_embedding=False))
    sentences = set(split_sentences(fold))
    leaked = (set(result.accepted) | set(result.rejected)) - sentences
    assert not leaked, f"phantom sentences in output: {leaked}"


def test_threshold_boundary_inclusive_at_default():
    """At cosine == 0.85, sentence should be accepted (>=, not >).

    Mutation: author uses '> threshold' instead of '>=' -> exact-boundary
    sentences are wrongly rejected.

    Strategy: inject embedding_fn that returns vectors with cosine ≈ 0.85
    for the test sentence vs first child.
    """
    import math

    # cos(theta) = 0.85 -> theta = acos(0.85)
    theta = math.acos(0.85)
    # Vector A = (1, 0); vector B = (cos theta, sin theta) -> cosine == 0.85
    vec_a = [1.0, 0.0]
    vec_b = [math.cos(theta), math.sin(theta)]

    call_log: list[str] = []

    async def fake_embedding(text: str):
        call_log.append(text)
        # First child gets vec_a; sentence and other inputs get vec_b
        # Use a deterministic mapping based on content.
        if text == "child block one":
            return vec_a
        return vec_b

    children = ["child block one"]
    # Sentence is NOT a substring of the child -> forced into embedding path.
    fold = "Totally different wording entirely."
    result = _run(
        verify_fold_extractiveness(
            fold,
            children,
            embedding_fn=fake_embedding,
            use_embedding=True,
            embedding_threshold=0.85,
        )
    )
    # At exactly 0.85 with >= boundary, sentence should accept.
    assert "Totally different wording entirely." in result.accepted, (
        f"threshold boundary 0.85 not inclusive (>=); accepted={result.accepted} "
        f"rejected={result.rejected}"
    )


def test_threshold_just_below_rejects():
    """At cosine slightly below threshold (e.g. 0.84), sentence rejected.

    Sanity-check the inverse to confirm threshold actually applies.
    """
    import math

    theta = math.acos(0.84)
    vec_a = [1.0, 0.0]
    vec_b = [math.cos(theta), math.sin(theta)]

    async def fake_embedding(text: str):
        if text == "child block one":
            return vec_a
        return vec_b

    children = ["child block one"]
    fold = "Totally different wording entirely."
    result = _run(
        verify_fold_extractiveness(
            fold,
            children,
            embedding_fn=fake_embedding,
            use_embedding=True,
            embedding_threshold=0.85,
        )
    )
    assert "Totally different wording entirely." in result.rejected


def test_empty_children_rejects_all_or_returns_empty_text():
    """children=[] is a degenerate case. Design choice:
       (A) reject all sentences (filtered_text == '')
       (B) raise ValueError

    We assert (A) — graceful degradation matches verifier's role as a
    safety net rather than an input validator.
    """
    children: list[str] = []
    fold = "Some sentence. Another sentence."
    try:
        result = _run(verify_fold_extractiveness(fold, children, use_embedding=False))
    except (ValueError, AssertionError):
        pytest.fail("verify_fold_extractiveness raised on empty children — "
                    "should reject all gracefully")
    assert result.accepted == []
    assert len(result.rejected) == 2


def test_empty_fold_text_returns_empty_result():
    """Empty fold -> nothing to verify. Must not crash, must return empty
    accepted/rejected (since split_sentences('') == [])."""
    result = _run(verify_fold_extractiveness("", ["some child"], use_embedding=False))
    assert result.accepted == []
    assert result.rejected == []
    assert result.filtered_text == ""


def test_filtered_text_contains_only_accepted():
    """filtered_text must reflect accepted-only content.

    Mutation: author returns original fold_text -> rejected sentences leak
    into downstream consumers.
    """
    children = ["Alfred is a butler."]
    fold = "Alfred is a butler. Moon is cheese."
    result = _run(verify_fold_extractiveness(fold, children, use_embedding=False))
    # The rejected sentence must NOT appear in filtered_text.
    assert "Moon is cheese" not in result.filtered_text, (
        f"rejected sentence leaked into filtered_text: {result.filtered_text!r}"
    )
    assert "Alfred is a butler" in result.filtered_text


def test_use_embedding_false_does_not_call_embedding_fn():
    """When use_embedding=False, embedding_fn must be skipped entirely.

    Mutation: author always calls embedding_fn -> wasted compute or crash
    when embedding_fn is None and substring fails.
    """
    calls: list[str] = []

    async def spy_embedding(text: str):
        calls.append(text)
        return [1.0, 0.0]

    children = ["completely unrelated"]
    fold = "Alfred is a butler."  # no substring match
    _ = _run(
        verify_fold_extractiveness(
            fold, children, use_embedding=False, embedding_fn=spy_embedding
        )
    )
    assert calls == [], f"embedding_fn called despite use_embedding=False: {calls}"

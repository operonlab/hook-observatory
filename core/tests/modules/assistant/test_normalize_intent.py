"""Mutation-aware tests for query_router.normalize_intent.

六鐵律:
1. Mutation thinking — 'mixed' 優先勝 memory/doc 是最容易被 mutation 殺掉的不變量
2. Independent from implementation — only contract-level assertions
3. Invariants over fixed I/O — output always in {"memory","doc","mixed"}
4. Mock only external I/O — normalize_intent is pure, no mocks needed
5. Error paths covered — empty, whitespace, garbage all → "mixed"
6. Docstring contract confirmed — commit 6e7eb08c: 'mixed wins when ambiguous'
"""

from __future__ import annotations

import pytest
from src.modules.assistant.ops.query_router import normalize_intent


# ═══════════════════════════════════════════════════════════════════════════
# Invariant: output set
# ═══════════════════════════════════════════════════════════════════════════

VALID_INTENTS = {"memory", "doc", "mixed"}


@pytest.mark.parametrize(
    "raw",
    [
        "memory",
        "Memory",
        "MEMORY",
        "doc",
        "DOC",
        "Doc only",
        "mixed",
        "MIXED",
        "foo bar",
        "",
        "   ",
        "memory please",
        "doc only",
        "mixed (both)",
        "answer: mixed because both",
        "I think memory is mixed",
        "irrelevant garbage 12345",
    ],
)
def test_output_always_in_valid_set(raw: str) -> None:
    """normalize_intent MUST return one of the three valid intent literals."""
    result = normalize_intent(raw)
    assert result in VALID_INTENTS, f"Got {result!r} for input {raw!r}"


# ═══════════════════════════════════════════════════════════════════════════
# Empty / whitespace → "mixed"
# ═══════════════════════════════════════════════════════════════════════════


def test_empty_string_returns_mixed() -> None:
    assert normalize_intent("") == "mixed"


def test_whitespace_only_returns_mixed() -> None:
    assert normalize_intent("   ") == "mixed"
    assert normalize_intent("\t\n") == "mixed"


# ═══════════════════════════════════════════════════════════════════════════
# Exact keyword matches
# ═══════════════════════════════════════════════════════════════════════════


def test_bare_memory_returns_memory() -> None:
    assert normalize_intent("memory") == "memory"


def test_uppercase_memory_returns_memory() -> None:
    assert normalize_intent("MEMORY") == "memory"


def test_mixed_case_memory_returns_memory() -> None:
    assert normalize_intent("Memory") == "memory"


def test_memory_phrase_returns_memory() -> None:
    assert normalize_intent("memory please") == "memory"


def test_bare_doc_returns_doc() -> None:
    assert normalize_intent("doc") == "doc"


def test_uppercase_doc_returns_doc() -> None:
    assert normalize_intent("DOC") == "doc"


def test_doc_phrase_returns_doc() -> None:
    assert normalize_intent("doc only") == "doc"


def test_bare_mixed_returns_mixed() -> None:
    assert normalize_intent("mixed") == "mixed"


def test_uppercase_mixed_returns_mixed() -> None:
    assert normalize_intent("MIXED") == "mixed"


def test_mixed_phrase_returns_mixed() -> None:
    assert normalize_intent("mixed (both)") == "mixed"


# ═══════════════════════════════════════════════════════════════════════════
# KILLER: mixed MUST beat memory when both substrings present
#
# Mutation scenario: if an implementation checks 'memory' before 'mixed',
# 'I think memory is mixed' → would return "memory" instead of "mixed".
# Commit 6e7eb08c docstring explicitly states 'mixed' is checked first.
# ═══════════════════════════════════════════════════════════════════════════


def test_mixed_beats_memory_when_both_present() -> None:
    """'mixed' keyword must win even when 'memory' substring also appears."""
    result = normalize_intent("I think memory is mixed")
    assert result == "mixed", (
        f"Expected 'mixed' but got {result!r}. "
        "If 'memory' check runs before 'mixed', this input hits the wrong branch."
    )


def test_mixed_beats_doc_when_both_present() -> None:
    """'mixed' keyword must win even when 'doc' substring also appears."""
    result = normalize_intent("this doc needs mixed retrieval")
    assert result == "mixed", (
        f"Expected 'mixed' but got {result!r}. "
        "If 'doc' check runs before 'mixed', this input hits the wrong branch."
    )


def test_answer_mixed_because_both() -> None:
    """LLM might verbosely say 'answer: mixed because both' — must normalize to 'mixed'."""
    assert normalize_intent("answer: mixed because both") == "mixed"


def test_mixed_prefix_long_sentence() -> None:
    """'mixed' at start of longer string → still 'mixed'."""
    assert normalize_intent("mixed: both memory and document sources are relevant") == "mixed"


# ═══════════════════════════════════════════════════════════════════════════
# Garbage input → "mixed" fallback
# ═══════════════════════════════════════════════════════════════════════════


def test_garbage_returns_mixed() -> None:
    assert normalize_intent("foo bar") == "mixed"


def test_numeric_garbage_returns_mixed() -> None:
    assert normalize_intent("12345") == "mixed"


def test_special_chars_returns_mixed() -> None:
    assert normalize_intent("!@#$%") == "mixed"


# ═══════════════════════════════════════════════════════════════════════════
# Pure-function property: same input → same output (determinism)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("raw", ["memory", "doc", "mixed", "", "garbage"])
def test_normalize_is_deterministic(raw: str) -> None:
    assert normalize_intent(raw) == normalize_intent(raw)

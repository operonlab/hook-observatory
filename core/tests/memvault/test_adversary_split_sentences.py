"""Adversary tests for split_sentences.

Mutation thinking targets:
- author splits naively on '.' -> 'Mr. Smith' becomes 2 sentences
- author splits on '.!?' but skips CJK '。！？' -> CJK input returns 1 sentence
- author returns [''] on empty -> downstream invariants break (len mismatch)
- author splits on '...' as 3 boundaries -> ellipsis becomes 4 fragments
- author keeps trailing whitespace -> set/dict keys mismatch
"""
# ruff: noqa: RUF001, RUF002

from src.modules.memvault.fold_verifier import split_sentences


def test_split_empty_returns_empty_list():
    """Mutation: returning [''] would break verifier invariants downstream."""
    assert split_sentences("") == []


def test_split_whitespace_only_returns_empty_list():
    """Pure whitespace must collapse to []."""
    out = split_sentences("   \n\t  ")
    assert out == []


def test_split_cjk_full_stops_three_sentences():
    """CJK punctuation must terminate sentences.

    Mutation: author only splits on '.!?' (Western) -> all 3 collapse to 1.
    """
    out = split_sentences("這是第一句。這是第二句！這是第三句？")
    assert len(out) == 3, f"expected 3 sentences, got {out}"


def test_split_western_three_sentences():
    """Baseline Western. Mutation: missing one of [.!?] drops a boundary."""
    out = split_sentences("First one. Second one! Third one?")
    assert len(out) == 3


def test_split_strips_each_sentence():
    """Sentences must be whitespace-stripped (docstring: 'Strips whitespace')."""
    out = split_sentences("  Hello world.  Another one.  ")
    for s in out:
        assert s == s.strip(), f"sentence not stripped: {s!r}"
        assert s, "empty sentence in output"


def test_split_abbreviation_mr_smith_known_limitation():
    """'Mr. Smith said hi.' — semantically 1 sentence, but naive splitters
    yield 2.

    This is a CLASSIC abbreviation problem. We assert the conservative
    expectation (1 sentence) so that if the author later adds a fix, we
    catch it. If the test fails today, that documents the known limitation.
    """
    out = split_sentences("Mr. Smith said hi.")
    # If the author handles abbreviations, this stays 1 sentence.
    # If naive split, this becomes 2 ('Mr', 'Smith said hi').
    assert len(out) == 1, (
        f"split_sentences over-splits 'Mr. Smith said hi.' into {out} — "
        f"abbreviation handling missing"
    )


def test_split_ellipsis_not_split_into_fragments():
    """'one... two.' should be 2 sentences, not 4.

    Mutation: author treats each '.' as a boundary -> 'one', '', '', ' two' (4).
    """
    out = split_sentences("one... two.")
    # Tolerant: must NOT explode into 4. Either 1 or 2 is acceptable design.
    assert len(out) <= 2, (
        f"ellipsis exploded into too many fragments: {out}"
    )
    # And no empty strings should leak.
    assert all(s for s in out), f"empty fragment from ellipsis: {out}"


def test_split_no_terminator_single_sentence():
    """Text without any terminator should be returned as one sentence,
    not dropped. Mutation: author requires '.' to keep -> drops the line.
    """
    out = split_sentences("no terminator here")
    assert len(out) == 1
    assert out[0] == "no terminator here"


def test_split_mixed_bilingual():
    """Mix CJK + Western — both terminators recognized in same string."""
    out = split_sentences("Hello world. 你好世界。")
    assert len(out) == 2

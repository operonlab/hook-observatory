"""Adversary tests for compute_fold_id.

Mutation thinking targets:
- author drops sorted() -> permutation invariance breaks
- author dedups silently -> [a,a,b] == [a,b] (design-decided here)
- empty list -> sentinel (must not collide with non-empty)
- author truncates differently -> length stability
"""

from src.modules.memvault.fold_verifier import compute_fold_id


def test_fold_id_permutation_invariant_three_children():
    """Mutation: if author removes sorted(), this fails."""
    a = compute_fold_id(["b1", "b2", "b3"])
    b = compute_fold_id(["b3", "b1", "b2"])
    c = compute_fold_id(["b2", "b3", "b1"])
    assert a == b == c


def test_fold_id_empty_list_is_distinct_sentinel():
    """Empty children must NOT collide with any non-empty fold_id.

    Mutation: author falls back to hashing literal '' which would still
    produce a deterministic 16-hex string, but it must differ from any
    list with content.
    """
    empty = compute_fold_id([])
    one = compute_fold_id(["b1"])
    assert empty != one
    assert isinstance(empty, str)
    assert len(empty) == 16  # sha256[:16]


def test_fold_id_duplicate_children_distinguishable_from_dedup():
    """Design decision: does [a,a,b] == [a,b]?

    Author's two reasonable options:
      (A) raw sorted join: hashes differ ('a|a|b' vs 'a|b')
      (B) dedup-then-sort: hashes equal

    The implementation should pick one and stick with it. We assert (A) —
    the sha256(sorted(children_block_ids)) doc says 'sorted', not 'set'.
    If author silently dedups, this catches it.
    """
    dup = compute_fold_id(["b1", "b1", "b2"])
    uniq = compute_fold_id(["b1", "b2"])
    # Strict: duplicates should be preserved by the sort -> different hash.
    assert dup != uniq, (
        "compute_fold_id appears to dedup children; design says sorted(), not set()"
    )


def test_fold_id_unicode_children_stable():
    """CJK / Unicode block ids must hash deterministically and not collide."""
    a = compute_fold_id(["區塊一", "區塊二"])
    b = compute_fold_id(["區塊二", "區塊一"])
    c = compute_fold_id(["block_1", "block_2"])
    assert a == b
    assert a != c
    assert len(a) == 16


def test_fold_id_long_list_stable_and_hex():
    """1000-entry list still produces fixed 16-hex output, permutation-stable."""
    big = [f"b{i:04d}" for i in range(1000)]
    rev = list(reversed(big))
    out_a = compute_fold_id(big)
    out_b = compute_fold_id(rev)
    assert out_a == out_b
    assert len(out_a) == 16
    int(out_a, 16)  # must parse as hex


def test_fold_id_returns_string_type():
    """Mutation: author returns bytes -> downstream JSON serialization breaks."""
    out = compute_fold_id(["b1"])
    assert isinstance(out, str)


def test_fold_id_single_child_distinct_from_empty():
    """Edge: 1-element list must not collide with empty sentinel."""
    assert compute_fold_id(["only"]) != compute_fold_id([])
